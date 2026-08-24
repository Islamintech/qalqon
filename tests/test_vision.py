"""Profile-photo screening.

The endpoint this talks to has already moved once — the old
api-inference.huggingface.co host stopped resolving entirely, and because the
original client swallowed every exception into a CLEAN verdict, that failure was
invisible. These tests pin the behaviour that makes the next move survivable.
"""
import httpx
import pytest

from conftest import FakeContext, FakeLLM, FakeMessage, FakeProfiles, FakeUpdate
from models import Risk, Verdict
from models.vision_client import HF_ROUTER, VisionClient
from test_controller import build

PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def patch_httpx(monkeypatch):
    def _apply(handler):
        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs.setdefault("transport", transport)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    return _apply


def json_response(nsfw: float, normal: float | None = None):
    normal = 1.0 - nsfw if normal is None else normal
    return httpx.Response(
        200,
        json=[{"label": "nsfw", "score": nsfw}, {"label": "normal", "score": normal}],
    )


# --- the endpoint ----------------------------------------------------------
def test_uses_the_router_host_not_the_dead_one():
    """api-inference.huggingface.co no longer resolves; pointing there fails
    100% of the time."""
    vc = VisionClient("token")
    assert vc._url.startswith(HF_ROUTER)
    assert "router.huggingface.co" in vc._url
    assert "api-inference" not in vc._url


# --- scoring ---------------------------------------------------------------
async def test_a_clearly_explicit_photo_is_a_red_flag(patch_httpx):
    patch_httpx(lambda req: json_response(0.98))
    assert (await VisionClient("t").classify_image(PNG)).risk is Risk.RED_FLAG


async def test_an_ordinary_photo_is_clean(patch_httpx):
    patch_httpx(lambda req: json_response(0.02))
    assert (await VisionClient("t").classify_image(PNG)).risk is Risk.CLEAN


async def test_a_borderline_score_is_fifty_fifty(patch_httpx):
    patch_httpx(lambda req: json_response(0.55))
    assert (await VisionClient("t").classify_image(PNG)).risk is Risk.FIFTY_FIFTY


async def test_the_threshold_is_configurable(patch_httpx):
    patch_httpx(lambda req: json_response(0.5))
    strict = await VisionClient("t", nsfw_threshold=0.4).classify_image(PNG)
    lax = await VisionClient("t", nsfw_threshold=0.95).classify_image(PNG)
    assert strict.risk is Risk.RED_FLAG
    assert lax.risk is not Risk.RED_FLAG


async def test_a_good_result_is_not_marked_degraded(patch_httpx):
    patch_httpx(lambda req: json_response(0.01))
    assert (await VisionClient("t").classify_image(PNG)).degraded is False


# --- failure is loud, not silent -------------------------------------------
async def test_a_dead_endpoint_is_reported_as_degraded(patch_httpx):
    """THE BUG THIS EXISTS FOR: the old client returned a plain CLEAN here, so
    a permanently broken endpoint looked exactly like a clean photo."""

    def boom(request):
        raise httpx.ConnectError("getaddrinfo failed")

    patch_httpx(boom)
    verdict = await VisionClient("t").classify_image(PNG)
    assert verdict.risk is Risk.CLEAN, "must not punish anyone for our outage"
    assert verdict.degraded is True, "but must not pretend it screened the photo"


async def test_a_bad_token_explains_itself(patch_httpx):
    patch_httpx(lambda req: httpx.Response(401, json={"error": "unauthorized"}))
    verdict = await VisionClient("t").classify_image(PNG)
    assert verdict.degraded is True
    assert "fine-grained" in verdict.reason, "tell the admin how to fix it"


async def test_an_unreadable_response_is_degraded_not_clean(patch_httpx):
    patch_httpx(lambda req: httpx.Response(200, json={"error": "model loading"}))
    verdict = await VisionClient("t").classify_image(PNG)
    assert verdict.degraded is True


async def test_a_cold_start_is_retried(patch_httpx):
    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "loading"})
        return json_response(0.01)

    patch_httpx(flaky)
    verdict = await VisionClient("t").classify_image(PNG)
    assert len(calls) == 2, "a 503 cold start should be retried once"
    assert verdict.degraded is False and verdict.risk is Risk.CLEAN


# --- propagation through the pipeline --------------------------------------
def test_degradation_is_sticky_through_worst():
    """A degraded component must taint the combined verdict, or the controller
    would never learn that a signal was missing."""
    combined = Verdict.worst(
        Verdict(Risk.CLEAN, "vision unavailable", "vision", degraded=True),
        Verdict(Risk.FIFTY_FIFTY, "keyword hit", "keyword"),
    )
    assert combined.risk is Risk.FIFTY_FIFTY and combined.degraded is True


class DegradedProfiles:
    def attach(self, bot):
        pass

    async def analyze(self, user_id):
        return Verdict(
            Risk.CLEAN, "vision unavailable: DNS", "profile", degraded=True
        )


async def test_broken_photo_screening_reaches_the_admins(store, bot):
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG), DegradedProfiles(), bot=bot)
    msg = FakeMessage(text="guaranteed profit, dm me to invest today")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    warnings = [t for _, t, _ in bot.sent if "DEGRADED" in t]
    assert warnings, "a dead vision endpoint must not fail silently"
    assert "photo screening" in warnings[0]


async def test_llm_and_vision_outages_are_reported_separately(store, bot):
    """Different subsystems, different outages — one must not mute the other."""
    class DeadLLM:
        async def analyze(self, text, context=""):
            return Verdict(Risk.CLEAN, "llm unavailable: 429", "llm", degraded=True)

    controller, _ = build(store, DeadLLM(), DegradedProfiles(), bot=bot)
    msg = FakeMessage(text="check out my profile for guaranteed profits")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    warned = " ".join(t for _, t, _ in bot.sent if "DEGRADED" in t)
    assert "language model" in warned and "photo screening" in warned


# --- the profile breakdown must account for every sub-check -----------------
class _Photos:
    def __init__(self, n): self.total_count = n; self.photos = []


class _ProfileBot:
    """Minimal bot surface ProfileAnalyzer touches."""

    def __init__(self, bio="", photos=0):
        self._bio, self._photos = bio, photos

    async def get_chat(self, user_id):
        class C: bio = self._bio
        return C()

    async def get_user_profile_photos(self, user_id, limit=1):
        return _Photos(self._photos)


class _NoChannel:
    def attach(self, bot):
        pass

    async def analyze(self, user_id):
        from models import Verdict, Risk
        return Verdict(Risk.CLEAN, "no linked channel", "channel")


async def test_every_profile_subcheck_appears_even_when_clean():
    """A clean bio used to append nothing, so the reviewer could not tell a
    clean bio from a bio that was never checked."""
    from models import ProfileAnalyzer

    analyzer = ProfileAnalyzer(vision=None, channel=_NoChannel())
    analyzer.attach(_ProfileBot(bio="just a normal person", photos=1))
    v = await analyzer.analyze(42)
    sources = [c.source for c in v.components]
    assert "bio" in sources and "photo" in sources and "channel" in sources
    assert v.risk is Risk.CLEAN


async def test_a_missing_photo_is_still_flagged():
    from models import ProfileAnalyzer

    analyzer = ProfileAnalyzer(vision=None, channel=_NoChannel())
    analyzer.attach(_ProfileBot(bio="", photos=0))
    v = await analyzer.analyze(42)
    assert v.risk is Risk.FIFTY_FIFTY
    assert "no profile photo" in v.breakdown()


async def test_a_scam_bio_is_caught_and_named():
    from models import ProfileAnalyzer

    analyzer = ProfileAnalyzer(vision=None, channel=_NoChannel())
    analyzer.attach(
        _ProfileBot(bio="crypto signals, guaranteed profit, dm for details", photos=1)
    )
    v = await analyzer.analyze(42)
    assert v.risk is Risk.RED_FLAG
    assert "bio" in v.breakdown()


async def test_screening_switched_off_is_distinguishable_from_a_clean_photo():
    """'screening off' and 'photo ok' must not look the same in an alert."""
    from models import ProfileAnalyzer

    analyzer = ProfileAnalyzer(vision=None, channel=_NoChannel())
    analyzer.attach(_ProfileBot(bio="hi", photos=1))
    v = await analyzer.analyze(42)
    assert "screening off" in v.breakdown()
