"""The verdict cache — the bot's main defence against paying twice.

This suite exists because the cache silently stopped working: analyze() only
stored a verdict when it was called with no sender context, and the model
always passes one, so the branch never ran. Nothing failed, nothing logged,
and every repeat of the same spam line cost a fresh call.

The rule the tests hold to: identical text judged under identical circumstances
is answered once. Different circumstances must still be judged separately —
one member's history must never colour another's verdict.
"""
import pytest

from models.llm_client import LLMClient
from models.verdict import Risk, Verdict

NEW = "SENDER CONTEXT: first message ever seen from this account."
ESTABLISHED = "SENDER CONTEXT: established member, no prior strikes."
SPAM = "send 500000 won deposit first and I will find you a job"


class CountingClient(LLMClient):
    """A real LLMClient with only the network call replaced."""

    def __init__(self, **kw):
        super().__init__("key", "model", **kw)
        self.real_calls = 0

    async def _call(self, user_content):
        self.real_calls += 1
        return Verdict(Risk.RED_FLAG, "advance-fee job offer", "llm")


@pytest.mark.asyncio
async def test_the_same_spam_from_the_same_kind_of_sender_costs_one_call():
    """The regression. A raid is many new accounts posting one line, so their
    sender context is identical too — that is exactly when caching must work."""
    c = CountingClient()
    for _ in range(20):
        await c.analyze(SPAM, context=NEW)
    assert c.real_calls == 1


@pytest.mark.asyncio
async def test_a_verdict_is_cached_even_when_context_is_given():
    c = CountingClient()
    await c.analyze(SPAM, context=NEW)
    assert len(c._cache) == 1, "the verdict was never stored"


@pytest.mark.asyncio
async def test_a_different_sender_context_is_judged_separately():
    """A brand-new account and a long-standing member saying the same thing are
    not the same question, so they must not share an answer."""
    c = CountingClient()
    await c.analyze(SPAM, context=NEW)
    await c.analyze(SPAM, context=ESTABLISHED)
    assert c.real_calls == 2


@pytest.mark.asyncio
async def test_different_text_is_never_shared():
    c = CountingClient()
    await c.analyze("hello everyone", context=NEW)
    await c.analyze(SPAM, context=NEW)
    assert c.real_calls == 2


@pytest.mark.asyncio
async def test_spacing_and_case_still_fold_together():
    """Scammers vary whitespace and capitals between reposts."""
    c = CountingClient()
    await c.analyze(SPAM, context=NEW)
    await c.analyze(f"  {SPAM.upper()}  ", context=NEW)
    assert c.real_calls == 1


@pytest.mark.asyncio
async def test_a_hit_is_reported_as_cached():
    c = CountingClient()
    await c.analyze(SPAM, context=NEW)
    await c.analyze(SPAM, context=NEW)
    assert c.last.cached is True
    assert c.last.prompt_tokens == 0, "a cached answer must not be billed"
    assert c.cache_hits == 1


@pytest.mark.asyncio
async def test_the_verdict_survives_the_round_trip():
    c = CountingClient()
    first = await c.analyze(SPAM, context=NEW)
    second = await c.analyze(SPAM, context=NEW)
    assert second.risk is first.risk is Risk.RED_FLAG
    assert "advance-fee job offer" in second.reason


@pytest.mark.asyncio
async def test_context_free_calls_still_cache():
    """The old behaviour was not wrong, only incomplete — keep it working."""
    c = CountingClient()
    await c.analyze(SPAM)
    await c.analyze(SPAM)
    assert c.real_calls == 1


@pytest.mark.asyncio
async def test_a_failed_call_is_not_cached():
    """Caching an outage would keep answering CLEAN long after Groq returned."""

    class Broken(CountingClient):
        async def _call(self, user_content):
            self.real_calls += 1
            raise RuntimeError("boom")

    c = Broken()
    first = await c.analyze(SPAM, context=NEW)
    assert first.degraded is True
    await c.analyze(SPAM, context=NEW)
    assert c.real_calls == 2, "the outage was cached"
