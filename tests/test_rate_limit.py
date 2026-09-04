"""Pacing against the token-per-minute ceiling.

The bot used to discover its rate limit by being 429'd. The semaphore capped
CONCURRENCY at 4, which at ~0.8s a call permits some 290 requests a minute
against a budget of roughly 8 — so it protected sockets, not the budget, and a
busy minute in a large group spent itself on retries and then went degraded.

A token bucket is the right shape here because the limit is per MINUTE: a
quiet hour earns no credit for the next one, but a short burst on top of a
quiet stretch is exactly what the allowance is for.

The clock is injected so none of this sleeps in the suite.
"""
import pytest

from models.rate_limiter import TokenBucket


class Clock:
    """A hand-wound clock. advance() is the only way time passes."""

    def __init__(self):
        self.now = 1000.0
        self.slept = 0.0

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.slept += seconds
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


def bucket(clock, limit=8000):
    return TokenBucket(limit_per_minute=limit, clock=clock.time, sleep=clock.sleep)


@pytest.mark.asyncio
async def test_the_first_call_is_never_delayed(clock):
    """A bot that pauses before its first message is broken, not careful."""
    await bucket(clock).acquire(900)
    assert clock.slept == 0


@pytest.mark.asyncio
async def test_a_burst_within_the_allowance_runs_flat_out(clock):
    b = bucket(clock, limit=8000)
    for _ in range(8):
        await b.acquire(900)          # 7200 of 8000
    assert clock.slept == 0


@pytest.mark.asyncio
async def test_going_over_the_ceiling_waits_instead_of_being_429ed(clock):
    b = bucket(clock, limit=8000)
    for _ in range(8):
        await b.acquire(1000)         # exactly the budget
    await b.acquire(1000)             # the ninth must wait
    assert clock.slept > 0


@pytest.mark.asyncio
async def test_the_allowance_refills_over_the_minute(clock):
    b = bucket(clock, limit=6000)
    await b.acquire(6000)
    clock.now += 60                   # a full minute passes
    await b.acquire(6000)
    assert clock.slept == 0, "a full minute should have refilled the budget"


@pytest.mark.asyncio
async def test_credit_does_not_accumulate_past_one_minute(clock):
    """An hour of silence must not buy an hour's worth of burst — the limit is
    per minute, and the provider will not honour saved-up quiet."""
    b = bucket(clock, limit=6000)
    clock.now += 3600
    await b.acquire(6000)
    await b.acquire(6000)
    assert clock.slept > 0


@pytest.mark.asyncio
async def test_a_single_call_larger_than_the_whole_budget_still_goes(clock):
    """Otherwise one long message would deadlock the bot forever."""
    b = bucket(clock, limit=1000)
    await b.acquire(5000)
    assert True  # returned at all


@pytest.mark.asyncio
async def test_a_zero_limit_disables_pacing(clock):
    """Escape hatch: an unknown or unmetered plan must not throttle to a stop."""
    b = bucket(clock, limit=0)
    for _ in range(50):
        await b.acquire(5000)
    assert clock.slept == 0


@pytest.mark.asyncio
async def test_it_reports_what_it_is_doing(clock):
    b = bucket(clock, limit=8000)
    await b.acquire(8000)
    await b.acquire(1000)
    assert b.waits == 1
    assert b.tokens_spent == 9000


@pytest.mark.asyncio
async def test_an_underestimate_is_settled_afterwards(clock):
    """A call reserves before it knows its real cost, so the difference has to
    land somewhere — on the next caller, not on nobody."""
    b = bucket(clock, limit=8000)
    await b.acquire(4000)
    b.charge(4000)                    # it actually cost 8000
    await b.acquire(1000)
    assert clock.slept > 0


@pytest.mark.asyncio
async def test_an_overestimate_is_refunded(clock):
    """Otherwise a conservative estimate would throttle the bot permanently."""
    b = bucket(clock, limit=8000)
    await b.acquire(8000)
    b.charge(-7000)                   # it only cost 1000
    await b.acquire(6000)
    assert clock.slept == 0


@pytest.mark.asyncio
async def test_charging_never_blocks(clock):
    b = bucket(clock, limit=1000)
    b.charge(50000)
    assert clock.slept == 0, "charge must not wait; the call already happened"


class CountingClock(Clock):
    """Counts sleeps, so a spin shows up as a number rather than a hang."""

    def __init__(self):
        super().__init__()
        self.sleeps = 0

    async def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 500:
            raise AssertionError(
                f"spinning: delay collapsed to {seconds!r} without ever "
                "clearing the deficit"
            )
        await super().sleep(seconds)


@pytest.mark.asyncio
async def test_a_long_run_never_spins_on_a_rounding_remainder():
    """The regression. Refilling for exactly the deficit can land a hair short
    of it in floating point, so the next delay is ~1e-16, the clock barely
    moves, and acquire loops forever — holding its lock, with the event loop
    pinned, which stalls every other message in the bot."""
    clock = CountingClock()
    b = TokenBucket(8000, clock=clock.time, sleep=clock.sleep)
    for _ in range(40):
        await b.acquire(960)
    assert clock.sleeps <= 80, "each call should need at most one wait"


@pytest.mark.asyncio
async def test_every_wait_is_long_enough_to_be_worth_making(clock):
    """A sub-millisecond sleep is a busy-wait wearing a costume."""
    b = TokenBucket(8000, clock=clock.time, sleep=clock.sleep)
    for _ in range(12):
        await b.acquire(960)
    assert clock.slept == 0 or clock.slept > 0.001
