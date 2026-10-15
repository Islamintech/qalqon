"""Model failover. Free tiers limit each model separately, so one model being
rate-limited must send the message to the next one — not to keyword-only
moderation with a DEGRADED alert."""
import pytest

from models.llm_client import Fallback, LLMClient, CallStats
from models.rate_limiter import TokenBucket
from models.verdict import Risk

REPLY = '{"risk": "RED_FLAG", "reason": "advance fee"}'


class ScriptedClient(LLMClient):
    """A real LLMClient whose network call fails for chosen backends."""

    def __init__(self, failing: dict[str, Exception], **kw):
        super().__init__("key", "primary", cache_ttl=0, **kw)
        self.failing = failing
        self.asked: list[str] = []

    async def _complete(self, backend, user_content):
        self.asked.append(backend.model)
        if backend.model in self.failing:
            raise self.failing[backend.model]
        return REPLY, CallStats(model=backend.model)


async def _no_sleep(_):
    return None


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    monkeypatch.setattr("models.llm_client.asyncio.sleep", _no_sleep)


@pytest.mark.asyncio
async def test_a_rate_limited_model_hands_over_to_the_next_at_once():
    c = ScriptedClient(
        {"primary": RuntimeError("Error code: 429 rate_limit_exceeded")},
        fallback_models=("second",),
    )
    v = await c.analyze("send a deposit first")
    assert v.risk is Risk.RED_FLAG and not v.degraded
    # One try on the primary, no backoff retries before moving on.
    assert c.asked == ["primary", "second"]
    assert c.last.model == "second"


@pytest.mark.asyncio
async def test_the_other_provider_is_tried_after_every_groq_model():
    c = ScriptedClient(
        {"primary": RuntimeError("429"), "second": RuntimeError("503")},
        fallback_models=("second",),
        fallback=Fallback("https://api.example/v1", "k", "other"),
    )
    v = await c.analyze("send a deposit first")
    assert not v.degraded
    assert c.asked == ["primary", "second", "other"]


@pytest.mark.asyncio
async def test_only_when_everything_fails_is_the_verdict_degraded():
    c = ScriptedClient(
        {"primary": RuntimeError("429"), "second": RuntimeError("429")},
        fallback_models=("second",),
    )
    v = await c.analyze("send a deposit first")
    assert v.degraded and v.risk is Risk.CLEAN
    assert "groq:primary" in v.reason and "groq:second" in v.reason
    # The last backend still gets its full set of retries.
    assert c.asked.count("second") == c._max_attempts


@pytest.mark.asyncio
async def test_a_spent_local_budget_skips_ahead_instead_of_waiting():
    c = ScriptedClient({}, fallback_models=("second",), token_limit_per_minute=100)
    assert c._backends[0].bucket.try_acquire(100)  # this minute is spent
    v = await c.analyze("send a deposit first")
    assert not v.degraded
    assert c.asked == ["second"], "the primary has no budget left this minute"


def test_an_incomplete_fallback_is_left_out():
    c = LLMClient("key", "primary", fallback=Fallback("", "", ""))
    assert [b.label for b in c._backends] == ["groq:primary"]


def test_try_acquire_never_waits():
    t = [0.0]
    bucket = TokenBucket(60, clock=lambda: t[0])
    assert bucket.try_acquire(60)
    assert not bucket.try_acquire(1)
    t[0] += 1.0  # one second refills one token at 60/min
    assert bucket.try_acquire(1)
