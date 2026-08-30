"""Usage accounting.

The interesting question is not what it costs — moderating 100,000 messages is
single-digit dollars. It is whether a busy minute exceeds the per-minute token
ceiling, because past that Qalqon is rate-limited and falls back to keyword
checks: still running, but no longer seeing subtle scams.
"""
import time
import uuid

import pytest

from models import Store
from web import pricing, queries


@pytest.fixture
async def seeded(tmp_path):
    s = Store(str(tmp_path / f"{uuid.uuid4().hex}.db"))
    await s.start()
    yield s
    await s.stop()


async def test_a_real_call_is_recorded(seeded):
    await seeded.record_usage(
        -1, model="m", prompt_tokens=700, completion_tokens=100, latency_ms=500
    )
    conn = queries.connect(seeded._path)
    u = queries.usage_summary(conn)
    conn.close()
    assert u["attempts"] == 1 and u["billed"] == 1
    assert u["total_tokens"] == 800 and u["avg_ms"] == 500


async def test_cache_hits_and_failures_are_counted_too(seeded):
    """Without the denominator the cache looks free and failures disappear."""
    await seeded.record_usage(-1, model="m", prompt_tokens=700, completion_tokens=100)
    await seeded.record_usage(-1, model="m", cached=True)
    await seeded.record_usage(-1, model="m", ok=False)
    conn = queries.connect(seeded._path)
    u = queries.usage_summary(conn)
    conn.close()
    assert u["attempts"] == 3, "every attempt counts"
    assert u["cached"] == 1 and u["failed"] == 1
    assert u["billed"] == 1, "only the real call is billable"


async def test_the_busiest_minute_is_found(seeded):
    """A quiet week with one busy minute still gets rate-limited, so the peak
    matters more than the total."""
    now = time.time()

    def _at(conn, ts, tok):
        conn.execute(
            "INSERT INTO usage (ts,chat_id,kind,model,prompt_tokens,"
            "completion_tokens,cached,ok) VALUES (?,?,'llm','m',?,0,0,1)",
            (ts, -1, tok),
        )
        conn.commit()

    for i in range(5):                      # five calls inside one minute
        await seeded._run(_at, now - 10, 2000)
    await seeded._run(_at, now - 7200, 500)  # a quiet hour earlier

    conn = queries.connect(seeded._path)
    peak = queries.busiest_minute(conn)
    conn.close()
    assert peak["tokens"] == 10000 and peak["calls"] == 5


async def test_cached_calls_do_not_count_toward_the_peak(seeded):
    """A cache hit sends nothing, so it cannot consume the rate limit."""
    now = time.time()

    def _cached(conn):
        conn.execute(
            "INSERT INTO usage (ts,chat_id,kind,model,prompt_tokens,"
            "completion_tokens,cached,ok) VALUES (?,?,'llm','m',9999,0,1,1)",
            (now, -1),
        )
        conn.commit()

    await seeded._run(lambda conn: _cached(conn))
    conn = queries.connect(seeded._path)
    assert queries.busiest_minute(conn)["tokens"] == 0
    conn.close()


async def test_usage_is_pruned_with_the_same_retention(tmp_path):
    """One row per analysed message means this grows faster than anything else
    in the database."""
    s = Store(str(tmp_path / "p.db"), event_retention_days=90)
    await s.start()
    await s.record_usage(-1, model="m", prompt_tokens=10)

    def _age(conn):
        conn.execute("UPDATE usage SET ts = ?", (time.time() - 200 * 86400,))
        conn.commit()

    await s._run(lambda conn: _age(conn))
    assert await s.prune_usage() == 1
    await s.stop()


# --- pricing ---------------------------------------------------------------
def test_an_unknown_model_costs_unknown_not_zero():
    """A missing price must never render as free — that would report every
    deployment as costing nothing."""
    assert pricing.cost("mystery", 1000, 100, {}) is None
    assert pricing.money(None) == "—"


def test_cost_uses_the_live_price_table():
    prices = {"m": {"prompt": 0.000000075, "completion": 0.0000003}}
    assert pricing.cost("m", 1_000_000, 0, prices) == pytest.approx(0.075)
    assert pricing.cost("m", 0, 1_000_000, prices) == pytest.approx(0.300)


def test_small_amounts_keep_their_digits():
    """Rounding to cents would print $0.00 for a month of moderation and make
    the figure look broken."""
    assert pricing.money(0.0026) == "$0.0026"
    assert pricing.money(0.115) == "$0.115"
    assert pricing.money(12.5) == "$12.50"


def test_cost_per_thousand_needs_billed_calls():
    prices = {"m": {"prompt": 1e-7, "completion": 1e-6}}
    assert pricing.per_thousand("m", {"billed": 0}, prices) is None
    got = pricing.per_thousand(
        "m", {"billed": 10, "prompt_tokens": 7000, "completion_tokens": 1000}, prices
    )
    assert got == pytest.approx(0.17)


# --- the dashboard must not invent a bill ----------------------------------
def test_free_tier_is_not_presented_as_money_owed():
    """Groq exposes no billing endpoint, so this cannot be detected. Printing
    a dollar figure for a free-tier key would be inventing a bill."""
    from web import pages

    base = {
        "usage": {
            "attempts": 10, "billed": 10, "cached": 0, "failed": 0,
            "prompt_tokens": 7000, "completion_tokens": 1000,
            "reasoning_tokens": 0, "total_tokens": 8000, "avg_ms": 500,
            "max_ms": 900, "avg_queue_ms": 10, "messages_seen": 40, "model": "m",
        },
        "prices": {"m": {"prompt": 1e-7, "completion": 1e-6}},
        "peak": {"tokens": 900, "calls": 2, "at": None},
        "days": 14, "model": "m", "token_limit": 8000,
        "usage_daily": [], "usage_by_chat": [], "chats": [],
    }
    free = pages.usage({**base, "billed": False})
    assert "not a bill" in free
    assert "list price equivalent" in free

    paid = pages.usage({**base, "billed": True})
    assert "not a bill" not in paid
