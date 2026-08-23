"""Strike decay: strikes stop counting toward escalation after decay_days.

The `ts` seam on add_strike lets these backdate strikes instead of sleeping.
"""
import sqlite3
import time
import uuid

import pytest

from conftest import FakeBot, FakeContext, FakeLLM, FakeProfiles, FakeUpdate, FakeUser
from models import Risk, Store
from models.store import DAY, STATUS_WHITELISTED
from test_controller import build, send


@pytest.fixture
async def decaying_store(tmp_path):
    s = Store(str(tmp_path / f"{uuid.uuid4().hex}.db"), decay_days=30)
    await s.start()
    yield s
    await s.stop()


async def test_fresh_strikes_count(decaying_store):
    await decaying_store.add_strike(1, 42)
    assert (await decaying_store.get(1, 42)).strikes == 1


async def test_expired_strikes_stop_counting(decaying_store):
    old = time.time() - 31 * DAY
    await decaying_store.add_strike(1, 42, ts=old)
    assert (await decaying_store.get(1, 42)).strikes == 0


async def test_strike_still_counts_on_the_last_day(decaying_store):
    """Off-by-one at the boundary is the whole risk here."""
    await decaying_store.add_strike(1, 42, ts=time.time() - 29 * DAY)
    assert (await decaying_store.get(1, 42)).strikes == 1


async def test_only_the_expired_ones_drop_off(decaying_store):
    await decaying_store.add_strike(1, 42, ts=time.time() - 40 * DAY)
    await decaying_store.add_strike(1, 42, ts=time.time() - 20 * DAY)
    await decaying_store.add_strike(1, 42)
    rec = await decaying_store.get(1, 42)
    assert rec.strikes == 2
    assert rec.lifetime_strikes == 3, "the lifetime total must never decay"


async def test_add_strike_returns_the_active_count(decaying_store):
    await decaying_store.add_strike(1, 42, ts=time.time() - 90 * DAY)
    assert await decaying_store.add_strike(1, 42) == 1


async def test_decay_can_be_disabled(tmp_path):
    s = Store(str(tmp_path / "never.db"), decay_days=0)
    await s.start()
    await s.add_strike(1, 42, ts=time.time() - 3650 * DAY)
    assert (await s.get(1, 42)).strikes == 1
    await s.stop()


async def test_expiry_time_is_reported_for_the_oldest_strike(decaying_store):
    await decaying_store.add_strike(1, 42, ts=time.time() - 10 * DAY)
    await decaying_store.add_strike(1, 42)
    rec = await decaying_store.get(1, 42)
    remaining = (rec.strikes_expire_at(30) - time.time()) / DAY
    assert 19.9 < remaining < 20.1, "should track the OLDEST active strike"


async def test_no_expiry_when_there_is_nothing_active(decaying_store):
    assert (await decaying_store.get(1, 42)).strikes_expire_at(30) is None


# --- interaction with trust and escalation ---------------------------------
async def test_decay_lets_a_member_earn_trust_back(decaying_store):
    """The point of decay: one bad week does not bar you forever."""
    await decaying_store.add_strike(1, 42, ts=time.time() - 60 * DAY)
    for _ in range(30):
        await decaying_store.touch(1, 42, "reformed")
    rec = await decaying_store.get(1, 42)
    assert rec.strikes == 0 and rec.trusted(min_messages=25)


async def test_active_strikes_still_block_trust(decaying_store):
    await decaying_store.add_strike(1, 42)
    for _ in range(30):
        await decaying_store.touch(1, 42, "recent offender")
    assert not (await decaying_store.get(1, 42)).trusted(min_messages=25)


async def test_old_strikes_do_not_escalate_a_new_offence(decaying_store, bot):
    """An offender from last year gets the first-offence response, not a ban."""
    controller, _ = build(
        decaying_store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.CLEAN),
        strikes_to_escalate=1,
    )
    await decaying_store.add_strike(-1001, 100, n=5, ts=time.time() - 200 * DAY)
    await send(controller, bot, "a fresh scam pitch to everyone here")
    assert bot.banned == [], "expired strikes must not push a first offence to a ban"
    assert bot.deleted, "it is still a red flag, so the message goes"


async def test_recent_strikes_do_escalate(decaying_store, bot):
    """The same scenario inside the window still escalates — proving the test
    above is about decay and not about something else being broken."""
    controller, _ = build(
        decaying_store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.CLEAN),
        strikes_to_escalate=1,
    )
    await decaying_store.add_strike(-1001, 100, n=5, ts=time.time() - 2 * DAY)
    await send(controller, bot, "a fresh scam pitch to everyone here")
    assert bot.banned == [(-1001, 100)]


# --- housekeeping ----------------------------------------------------------
async def test_prune_removes_expired_rows_only(decaying_store):
    await decaying_store.add_strike(1, 42, ts=time.time() - 90 * DAY)
    await decaying_store.add_strike(1, 43)
    # add_strike prunes opportunistically, so ask for what is left.
    assert (await decaying_store.get(1, 42)).strikes == 0
    assert (await decaying_store.get(1, 43)).strikes == 1


async def test_whitelisting_drops_active_strikes(decaying_store):
    await decaying_store.add_strike(1, 42, n=3)
    await decaying_store.set_status(1, 42, STATUS_WHITELISTED)
    assert (await decaying_store.get(1, 42)).strikes == 0


async def test_forgive_keeps_the_lifetime_record(decaying_store):
    await decaying_store.add_strike(1, 42, n=2)
    await decaying_store.clear_strikes(1, 42)
    rec = await decaying_store.get(1, 42)
    assert rec.strikes == 0
    assert rec.lifetime_strikes == 2, "history stays visible to admins"


async def test_stats_count_active_strikes_not_lifetime(decaying_store):
    await decaying_store.add_strike(1, 42, ts=time.time() - 90 * DAY)
    await decaying_store.add_strike(1, 43)
    s = await decaying_store.stats(1)
    assert s["users_with_strikes"] == 1 and s["active_strikes"] == 1


# --- migration from the pre-decay schema -----------------------------------
async def test_v1_database_is_migrated(tmp_path):
    """A v1 DB stored strikes as a bare counter. Those must survive the upgrade
    rather than silently vanishing (which would forgive every known offender)."""
    path = str(tmp_path / "v1.db")
    last_seen = time.time() - 5 * DAY
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '', messages_seen INTEGER NOT NULL DEFAULT 0,
            strikes INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'normal',
            first_seen REAL NOT NULL DEFAULT 0, last_seen REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id));
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, ts REAL NOT NULL, action TEXT NOT NULL,
            risk TEXT NOT NULL, reason TEXT NOT NULL, text TEXT NOT NULL DEFAULT '');
        """
    )
    conn.execute(
        "INSERT INTO users (chat_id,user_id,username,messages_seen,strikes,status,"
        "first_seen,last_seen) VALUES (7,99,'old',12,2,'normal',?,?)",
        (last_seen - DAY, last_seen),
    )
    conn.commit()
    conn.close()

    s = Store(path, decay_days=30)
    await s.start()
    rec = await s.get(7, 99)
    assert rec.strikes == 2, "existing strikes must carry over"
    assert rec.messages_seen == 12
    await s.stop()


async def test_migration_is_not_repeated_on_restart(tmp_path):
    """Running start() twice must not double every user's strikes."""
    path = str(tmp_path / "twice.db")
    s = Store(path, decay_days=30)
    await s.start()
    await s.add_strike(1, 42, n=2)
    await s.stop()

    s2 = Store(path, decay_days=30)
    await s2.start()
    assert (await s2.get(1, 42)).strikes == 2
    await s2.stop()
