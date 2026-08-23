"""Autonomy levels and the digest.

The problem these solve: one live alert per action is unreadable across many
groups, and unreadable means unread — which is worse than silence, because it
looks like oversight is happening when it is not.
"""
import pytest

from conftest import FakeContext, FakeLLM, FakeMessage, FakeProfiles, FakeUpdate
from models import Action, Autonomy, Risk
from views import DigestReporter


# --- what the bot is allowed to carry out ----------------------------------
@pytest.mark.parametrize("action", list(Action))
def test_report_mode_never_touches_the_chat(action):
    """Anything that would have acted is downgraded to REVIEW."""
    permitted = Autonomy.REPORT.permit(action)
    assert permitted.rank <= Action.REVIEW.rank


@pytest.mark.parametrize("mode", [Autonomy.ASSISTED, Autonomy.AUTONOMOUS])
@pytest.mark.parametrize("action", list(Action))
def test_acting_modes_do_not_second_guess_the_policy(mode, action):
    """Autonomy governs notification, not judgement — otherwise severity would
    be decided in two places."""
    assert mode.permit(action) is action


# --- who gets interrupted --------------------------------------------------
def test_assisted_interrupts_for_decisions_and_bans():
    a = Autonomy.ASSISTED
    assert a.alerts_live(Action.REVIEW) is True, "a human must actually decide"
    assert a.alerts_live(Action.BAN) is True, "reversible only if someone sees it"
    assert a.alerts_live(Action.DELETE) is False, "done, and low stakes"
    assert a.alerts_live(Action.NONE) is False


def test_autonomous_interrupts_for_nothing():
    for action in Action:
        assert Autonomy.AUTONOMOUS.alerts_live(action) is False


def test_report_interrupts_for_everything_it_finds():
    assert Autonomy.REPORT.alerts_live(Action.REVIEW) is True
    assert Autonomy.REPORT.alerts_live(Action.NONE) is False


def test_parse_falls_back_instead_of_crashing():
    """A typo in .env must not take the bot down on boot."""
    assert Autonomy.parse("nonsense") is Autonomy.ASSISTED
    assert Autonomy.parse("AUTONOMOUS") is Autonomy.AUTONOMOUS
    assert Autonomy.parse(" report ") is Autonomy.REPORT


# --- the digest ------------------------------------------------------------
class Sink:
    def __init__(self):
        self.messages = []

    async def __call__(self, body):
        self.messages.append(body)


async def test_a_quiet_period_sends_nothing():
    """A digest that says "nothing happened" every 6h is training to ignore it."""
    sink = Sink()
    assert await DigestReporter().flush(sink) is False
    assert sink.messages == []


async def test_entries_are_grouped_by_chat():
    """A flat timeline across twenty groups tells you nothing about WHICH
    community has a problem."""
    d = DigestReporter()
    await d.add(-100, "Crypto Chat", "BAN", "scammer1", 1, "investment pitch")
    await d.add(-100, "Crypto Chat", "BAN", "scammer2", 2, "airdrop link")
    await d.add(-200, "Book Club", "DELETE", "spammer", 3, "spam")
    sink = Sink()
    await d.flush(sink)
    body = sink.messages[0]
    assert "Crypto Chat" in body and "Book Club" in body
    assert "2× BAN" in body and "1× DELETE" in body


async def test_the_busiest_chat_comes_first():
    d = DigestReporter()
    await d.add(-200, "Quiet", "DELETE", "a", 1, "x")
    for i in range(5):
        await d.add(-100, "Busy", "BAN", f"u{i}", i, "x")
    sink = Sink()
    await d.flush(sink)
    body = sink.messages[0]
    assert body.index("Busy") < body.index("Quiet")


async def test_a_huge_chat_is_truncated_with_a_count():
    d = DigestReporter(max_lines_per_chat=3)
    for i in range(20):
        await d.add(-100, "Raided", "BAN", f"u{i}", i, "scam")
    sink = Sink()
    await d.flush(sink)
    assert "and 17 more" in sink.messages[0]
    assert "20× BAN" in sink.messages[0], "the COUNT must stay accurate"


async def test_flushing_clears_the_buffer():
    d = DigestReporter()
    await d.add(-100, "C", "BAN", "u", 1, "x")
    sink = Sink()
    await d.flush(sink)
    await d.flush(sink)
    assert len(sink.messages) == 1, "the second flush had nothing to say"


async def test_pending_counts_what_is_waiting():
    d = DigestReporter()
    assert d.pending == 0
    await d.add(-100, "C", "BAN", "u", 1, "x")
    await d.add(-100, "C", "DELETE", "u", 1, "x")
    assert d.pending == 2


async def test_stop_emits_the_partial_period():
    """A restart must not silently discard what happened since the last digest."""
    d = DigestReporter()
    await d.add(-100, "C", "BAN", "u", 1, "x")
    sink = Sink()
    await d.stop(sink)
    assert sink.messages, "pending actions must survive shutdown"


# --- through the controller ------------------------------------------------
def build_with(store, autonomy, digest, llm_risk=Risk.RED_FLAG,
               profile_risk=Risk.RED_FLAG):
    from controllers import ModerationController
    from models import FileScanner, KeywordFilter, LinkAnalyzer, Policy
    from views import AlertBatcher, TelegramView

    view = TelegramView(False, "999", batcher=AlertBatcher(threshold=10_000))
    return ModerationController(
        keyword_filter=KeywordFilter(),
        llm_client=FakeLLM(llm_risk),
        profile_analyzer=FakeProfiles(profile_risk),
        view=view, store=store, policy=Policy(), file_scanner=FileScanner(),
        link_analyzer=LinkAnalyzer(), digest=digest, autonomy=autonomy,
        skip_group_admins=False,
    )


async def send(controller, bot, text="guaranteed 300% returns, dm me now"):
    await controller.handle_message(
        FakeUpdate(FakeMessage(text=text)), FakeContext(bot)
    )


async def test_assisted_alerts_live_on_a_ban(store, bot):
    d = DigestReporter()
    await send(build_with(store, Autonomy.ASSISTED, d), bot)
    assert bot.sent, "a ban must be seen quickly enough to undo"
    assert d.pending == 0


async def test_assisted_digests_a_delete(store, bot):
    """Message gone, user stays — nobody needs a 3am ping for that."""
    d = DigestReporter()
    controller = build_with(store, Autonomy.ASSISTED, d, profile_risk=Risk.CLEAN)
    await send(controller, bot)
    assert bot.sent == [], "a routine delete should not interrupt anyone"
    assert d.pending == 1


async def test_autonomous_never_interrupts(store, bot):
    d = DigestReporter()
    await send(build_with(store, Autonomy.AUTONOMOUS, d), bot)
    assert bot.sent == []
    assert d.pending == 1


async def test_report_mode_acts_on_nothing(store, bot):
    d = DigestReporter()
    await send(build_with(store, Autonomy.REPORT, d), bot)
    assert bot.banned == [] and bot.deleted == [], "report mode must not act"
    assert bot.sent, "but it must still report"


async def test_without_a_digest_everything_still_alerts(store, bot):
    """Backwards compatible: no digest configured means no silent drops."""
    controller = build_with(store, Autonomy.ASSISTED, None, profile_risk=Risk.CLEAN)
    await send(controller, bot)
    assert bot.sent, "with nowhere to digest to, it must alert instead"
