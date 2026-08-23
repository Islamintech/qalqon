"""Raid defence: flood detection, raid detection, and alert coalescing."""
import pytest

from conftest import FakeContext, FakeLLM, FakeMessage, FakeProfiles, FakeUpdate, FakeUser
from models import BurstDetector, Risk
from views.alert_batcher import AlertBatcher
from test_controller import build


# --- per-user flood --------------------------------------------------------
def test_normal_pace_is_clean():
    d = BurstDetector(flood_messages=5, flood_window=8)
    for i in range(4):
        assert d.record(1, 42, now=1000.0 + i * 3).clean


def test_a_burst_raises_suspicion():
    d = BurstDetector(flood_messages=5, flood_window=8)
    verdicts = [d.record(1, 42, now=1000.0 + i * 0.5) for i in range(5)]
    assert verdicts[-1].risk is Risk.FIFTY_FIFTY


def test_a_severe_flood_is_a_red_flag():
    d = BurstDetector(flood_messages=5, flood_window=8)
    verdicts = [d.record(1, 42, now=1000.0 + i * 0.2) for i in range(10)]
    assert verdicts[-1].risk is Risk.RED_FLAG


def test_the_window_slides():
    """Messages spread out over time must not accumulate into a false flood."""
    d = BurstDetector(flood_messages=5, flood_window=8)
    for i in range(20):
        assert d.record(1, 42, now=1000.0 + i * 10).clean


def test_users_are_tracked_separately():
    d = BurstDetector(flood_messages=3, flood_window=8)
    for i in range(3):
        d.record(1, 42, now=1000.0 + i * 0.1)
    assert d.record(1, 99, now=1000.4).clean


def test_chats_are_tracked_separately():
    d = BurstDetector(flood_messages=3, flood_window=8)
    for i in range(3):
        d.record(1, 42, now=1000.0 + i * 0.1)
    assert d.record(2, 42, now=1000.4).clean


# --- raid ------------------------------------------------------------------
def test_a_wave_of_new_accounts_trips_raid_state():
    d = BurstDetector(raid_users=5, raid_window=60)
    tripped = [d.note_new_account(1, uid, now=1000.0 + uid) for uid in range(1, 6)]
    assert tripped[-1] is True, "the fifth new account should trip it"
    assert d.raid_active(1, now=1010.0)


def test_raid_state_only_announces_once():
    d = BurstDetector(raid_users=3, raid_window=60)
    tripped = [d.note_new_account(1, uid, now=1000.0 + uid) for uid in range(1, 10)]
    assert sum(tripped) == 1, "only the transition into a raid should announce"


def test_a_few_new_accounts_are_not_a_raid():
    d = BurstDetector(raid_users=5, raid_window=60)
    assert not any(d.note_new_account(1, uid, now=1000.0) for uid in range(1, 4))
    assert not d.raid_active(1, now=1000.0)


def test_the_same_account_repeating_is_not_a_raid():
    """Raid means many DIFFERENT accounts — one chatty newcomer is not one."""
    d = BurstDetector(raid_users=5, raid_window=60)
    assert not any(d.note_new_account(1, 42, now=1000.0 + i) for i in range(10))


def test_raid_state_expires():
    d = BurstDetector(raid_users=3, raid_window=60, raid_cooldown=300)
    for uid in range(1, 4):
        d.note_new_account(1, uid, now=1000.0)
    assert d.raid_active(1, now=1200.0)
    assert not d.raid_active(1, now=1400.0)


def test_prune_releases_memory():
    d = BurstDetector(flood_window=8, raid_window=60)
    for uid in range(50):
        d.record(1, uid, now=1000.0)
        d.note_new_account(1, uid, now=1000.0)
    d.prune(now=2000.0)
    assert d._user_times == {} and d._chat_joins == {}


# --- alert coalescing ------------------------------------------------------
class Collector:
    """The batcher's `send` is awaited, so tests need an async sink."""

    def __init__(self):
        self.messages = []

    async def __call__(self, body):
        self.messages.append(body)



async def test_quiet_alerts_are_sent_individually():
    """Below the threshold every alert keeps its buttons — that is the whole
    value of the review queue."""
    b = AlertBatcher(threshold=5, window=30)
    sent = Collector()
    for i in range(4):
        assert await b.submit(f"alert {i}", sent, now=1000.0 + i) is True
    await b.close()


async def test_a_flood_of_alerts_is_batched():
    b = AlertBatcher(threshold=5, window=30, flush_interval=999)
    sent = Collector()
    results = [await b.submit(f"alert {i}", sent, now=1000.0) for i in range(20)]
    assert results[:4] == [True] * 4, "the first few still go out individually"
    assert not any(results[4:]), "the rest are folded into a digest"
    await b.close()


async def test_the_digest_names_the_users():
    b = AlertBatcher(threshold=2, window=30, flush_interval=999)
    sent = Collector()
    for i in range(5):
        await b.submit(f"user {i} flagged", sent, now=1000.0)
    await b.flush(sent)
    await b.close()
    assert len(sent.messages) == 1
    assert "user 4 flagged" in sent.messages[0] and "digest" in sent.messages[0]


async def test_an_enormous_digest_is_truncated_with_a_count():
    """Telegram caps message length; a raid must not produce an unsendable one."""
    b = AlertBatcher(threshold=2, window=30, flush_interval=999, max_digest_lines=5)
    sent = Collector()
    for i in range(40):
        await b.submit(f"user {i}", sent, now=1000.0)
    await b.flush(sent)
    await b.close()
    assert "and 34 more" in sent.messages[0]


async def test_flush_with_nothing_pending_sends_nothing():
    b = AlertBatcher()
    sent = Collector()
    await b.flush(sent)
    assert sent.messages == []


# --- through the controller ------------------------------------------------
async def test_flooding_escalates_a_new_account(store, bot):
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles(Risk.RED_FLAG))
    for i in range(12):
        msg = FakeMessage(text=f"buy now message {i}", message_id=i)
        await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert bot.deleted, "a flood from a new account should be acted on"


async def test_an_established_member_may_post_quickly(store, bot):
    """A regular in a heated argument is not a spammer."""
    controller, _ = build(
        store, FakeLLM(Risk.CLEAN), FakeProfiles(Risk.RED_FLAG), trust_after=3
    )
    for _ in range(10):
        await store.touch(-1001, 100, "regular")
    for i in range(12):
        msg = FakeMessage(text=f"and another thing {i}", message_id=i)
        await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert bot.deleted == [] and bot.banned == []


async def test_a_raid_is_announced_to_admins(store, bot):
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles())
    for uid in range(200, 210):
        msg = FakeMessage(text="hello everyone here", user=FakeUser(uid, f"u{uid}"))
        await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    raid_alerts = [t for _, t, _ in bot.sent if "raid" in t.lower()]
    assert len(raid_alerts) == 1, "announce the raid once, not per account"


async def test_pace_alone_never_bans(store, bot):
    """Pace feeds the normal escalation path; it is not its own punishment."""
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles(Risk.CLEAN))
    for i in range(15):
        msg = FakeMessage(text=f"ordinary chatter {i}", message_id=i)
        await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert bot.banned == [], "a clean-profile fast poster must not be banned"
