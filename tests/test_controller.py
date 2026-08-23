"""End-to-end through the controller with fake Telegram/Groq, plus the store
and the admin surface."""
import pytest

from conftest import (
    FakeBot, FakeContext, FakeLLM, FakeMessage, FakeProfiles, FakeUpdate, FakeUser,
)
from controllers import AdminController, ModerationController
from models import FileScanner, KeywordFilter, Policy, Risk
from models.store import STATUS_BANNED, STATUS_WHITELISTED
from views import AlertBatcher, TelegramView
from views.telegram_view import build_callback


def build(store, llm, profiles, dry_run=False, trust_after=25, strikes_to_escalate=2):
    # A high batching threshold keeps these tests about MODERATION rather than
    # alert delivery — coalescing has its own tests in test_raid.py.
    view = TelegramView(
        dry_run=dry_run,
        admin_chat_id="999",
        batcher=AlertBatcher(threshold=10_000),
    )
    controller = ModerationController(
        keyword_filter=KeywordFilter(),
        llm_client=llm,
        profile_analyzer=profiles,
        view=view,
        store=store,
        policy=Policy(strikes_to_escalate=strikes_to_escalate),
        file_scanner=FileScanner(),
        trust_after_messages=trust_after,
    )
    return controller, view


async def send(controller, bot, text="hello", user=None, chat_id=-1001):
    msg = FakeMessage(text=text, user=user or FakeUser(), chat_id=chat_id)
    await controller.handle_message(FakeUpdate(msg, chat_id=chat_id), FakeContext(bot))
    return msg


# --- happy path ------------------------------------------------------------
async def test_clean_message_does_nothing(store, bot):
    llm, profiles = FakeLLM(Risk.CLEAN), FakeProfiles()
    controller, _ = build(store, llm, profiles)
    await send(controller, bot, "good morning")
    assert bot.deleted == [] and bot.banned == [] and bot.sent == []
    assert profiles.calls == 0, "a clean message must not cost a profile lookup"


async def test_clean_message_still_counts_toward_tenure(store, bot):
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles())
    for _ in range(3):
        await send(controller, bot, "hi")
    assert (await store.get(-1001, 100)).messages_seen == 3


# --- acting ----------------------------------------------------------------
async def test_red_content_plus_red_profile_bans(store, bot):
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.RED_FLAG))
    msg = await send(controller, bot, "invest now, guaranteed returns")
    assert bot.deleted == [(-1001, msg.message_id)]
    assert bot.banned == [(-1001, 100)]
    assert (await store.get(-1001, 100)).status == STATUS_BANNED


async def test_lone_red_flag_deletes_but_does_not_ban(store, bot):
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.CLEAN))
    await send(controller, bot, "send me money")
    assert bot.deleted and bot.banned == []


async def test_borderline_only_alerts_admins(store, bot):
    controller, _ = build(store, FakeLLM(Risk.FIFTY_FIFTY), FakeProfiles(Risk.CLEAN))
    await send(controller, bot, "dm me")
    assert bot.deleted == [] and bot.banned == []
    assert len(bot.sent) == 1
    chat_id, text, markup = bot.sent[0]
    assert chat_id == "999" and "Review" in text
    assert markup is not None, "an alert with no buttons is a dead end"


async def test_dry_run_touches_nothing_but_still_alerts(store, bot):
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.RED_FLAG), dry_run=True)
    await send(controller, bot, "send me your seed phrase to verify")
    assert bot.deleted == [] and bot.banned == []
    assert bot.sent and "[DRY-RUN]" in bot.sent[0][1]


# --- memory ----------------------------------------------------------------
async def test_repeat_offender_escalates_to_a_ban(store, bot):
    """Same borderline message three times: review, review, then removed."""
    controller, _ = build(
        store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.CLEAN), strikes_to_escalate=1
    )
    await send(controller, bot, "first scam attempt here")
    assert bot.banned == []
    await send(controller, bot, "second scam attempt here")
    assert bot.banned == [(-1001, 100)], "a second offence should escalate"


async def test_trusted_member_is_not_auto_banned(store, bot):
    controller, _ = build(
        store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.RED_FLAG), trust_after=3
    )
    for _ in range(4):
        await store.touch(-1001, 100, "regular")
    await send(controller, bot, "guaranteed profit, invest with me")
    assert bot.banned == [], "an established member must get a human review"
    assert bot.sent and "Review" in bot.sent[0][1]


async def test_whitelisted_user_skips_the_pipeline(store, bot):
    llm = FakeLLM(Risk.RED_FLAG)
    controller, _ = build(store, llm, FakeProfiles(Risk.RED_FLAG))
    await store.set_status(-1001, 100, STATUS_WHITELISTED)
    await send(controller, bot, "obvious scam text")
    assert bot.banned == [] and bot.deleted == [] and bot.sent == []
    assert llm.calls == [], "a whitelisted user must not cost an LLM call"


@pytest.mark.parametrize("text", ["ok", "thanks!", "👍", "lol same"])
async def test_short_chatter_costs_no_llm_call(store, bot, text):
    llm = FakeLLM(Risk.CLEAN)
    controller, _ = build(store, llm, FakeProfiles())
    await send(controller, bot, text)
    assert llm.calls == []


@pytest.mark.parametrize("text", ["t.me/x", "@me", "http://a.io"])
async def test_short_message_with_a_link_still_gets_checked(store, bot, text):
    """Short is only safe when there is nothing to click."""
    llm = FakeLLM(Risk.CLEAN)
    controller, _ = build(store, llm, FakeProfiles())
    await send(controller, bot, text)
    assert len(llm.calls) == 1


async def test_established_member_is_still_analyzed(store, bot):
    """Tenure caps the punishment; it must not buy invisibility. A long-standing
    account that gets compromised is exactly what a tenure-skip would miss."""
    llm = FakeLLM(Risk.RED_FLAG)
    controller, _ = build(store, llm, FakeProfiles(Risk.RED_FLAG), trust_after=3)
    for _ in range(5):
        await store.touch(-1001, 100, "regular")
    await send(controller, bot, "guaranteed profit, dm me to invest today")
    assert len(llm.calls) == 1
    assert bot.banned == []
    assert bot.sent and "Review" in bot.sent[0][1]


async def test_sender_context_reaches_the_model(store, bot):
    llm = FakeLLM(Risk.CLEAN)
    controller, _ = build(store, llm, FakeProfiles())
    await send(controller, bot, "hello everybody, how are you all")
    assert "first message ever" in llm.calls[0][1]


async def test_bots_are_ignored(store, bot):
    llm = FakeLLM(Risk.RED_FLAG)
    controller, _ = build(store, llm, FakeProfiles(Risk.RED_FLAG))
    await send(controller, bot, "obvious scam pitch here",
               user=FakeUser(200, "otherbot", is_bot=True))
    assert llm.calls == [] and bot.banned == []


async def test_alerts_show_every_signal_not_just_the_winner(store, bot):
    """A reviewer needs to know whether one detector fired or several agreed."""
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG, "model says scam"),
                          FakeProfiles(Risk.CLEAN))
    msg = FakeMessage(text="hey check out my profile, guaranteed returns")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    body = bot.sent[0][1]
    assert "llm" in body and "keyword" in body and "link" in body
    assert "model says scam" in body


async def test_a_non_firing_detector_is_still_listed(store, bot):
    """Showing that the keyword pass ran and found nothing is information."""
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.CLEAN))
    msg = FakeMessage(text="an entirely novel scam the regexes do not know")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert "no pattern matched" in bot.sent[0][1]


# --- admin surface ---------------------------------------------------------
async def test_button_requires_authorization(store, bot):
    _, view = build(store, FakeLLM(), FakeProfiles())
    admin = AdminController(store, view, admin_chat_id="999")
    answered = []

    class Query:
        data = build_callback("ban", -1001, 100)
        message = FakeMessage(text="alert")

        async def answer(self, text=None, show_alert=False):
            answered.append(text)

        async def edit_message_text(self, text):
            pass

    update = FakeUpdate(user=FakeUser(555, "randomer"), chat_id=-1001,
                        callback_query=Query())
    await admin.on_button(update, FakeContext(bot))
    assert bot.banned == [], "a non-admin must not be able to ban"
    assert answered == ["not authorized"]


async def test_admin_button_bans(store, bot):
    bot.admins.add(555)
    _, view = build(store, FakeLLM(), FakeProfiles())
    admin = AdminController(store, view, admin_chat_id="999")

    class Query:
        data = build_callback("ban", -1001, 100)
        message = FakeMessage(text="alert")

        async def answer(self, text=None, show_alert=False):
            pass

        async def edit_message_text(self, text):
            self.edited = text

    update = FakeUpdate(user=FakeUser(555, "boss"), chat_id=-1001, callback_query=Query())
    await admin.on_button(update, FakeContext(bot))
    assert bot.banned == [(-1001, 100)]
    assert (await store.get(-1001, 100)).status == STATUS_BANNED


async def test_ignore_button_clears_strikes(store, bot):
    """A false positive must not leave a strike that escalates the next one."""
    bot.admins.add(555)
    _, view = build(store, FakeLLM(), FakeProfiles())
    admin = AdminController(store, view, admin_chat_id="999")
    await store.add_strike(-1001, 100, 2)

    class Query:
        data = build_callback("ok", -1001, 100)
        message = FakeMessage(text="alert")

        async def answer(self, text=None, show_alert=False):
            pass

        async def edit_message_text(self, text):
            pass

    await admin.on_button(
        FakeUpdate(user=FakeUser(555), chat_id=-1001, callback_query=Query()),
        FakeContext(bot),
    )
    assert (await store.get(-1001, 100)).strikes == 0


async def test_dryrun_command_is_admin_only(store, bot):
    _, view = build(store, FakeLLM(), FakeProfiles(), dry_run=True)
    admin = AdminController(store, view, admin_chat_id="999")
    msg = FakeMessage(text="/dryrun off", user=FakeUser(555, "randomer"))
    await admin.dryrun(FakeUpdate(msg, chat_id=-1001), FakeContext(bot, args=["off"]))
    assert view.dry_run is True, "a non-admin must not be able to go live"

    bot.admins.add(555)
    await admin.dryrun(FakeUpdate(msg, chat_id=-1001), FakeContext(bot, args=["off"]))
    assert view.dry_run is False


# --- files -----------------------------------------------------------------
class _Doc:
    """Shared with test_bypasses."""

    def __init__(self, file_name, mime_type=None, file_size=1000):
        self.file_name = file_name
        self.mime_type = mime_type
        self.file_size = file_size


async def test_dangerous_file_is_removed_without_a_profile_check(store, bot):
    profiles = FakeProfiles(Risk.CLEAN)
    controller, _ = build(store, FakeLLM(), profiles)
    msg = FakeMessage(text=None, document=_Doc("wallet.apk", "application/vnd.android.package-archive"))
    for attr in ("animation", "video", "audio", "voice", "video_note"):
        setattr(msg, attr, None)
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert bot.deleted == [(-1001, 7)]
    assert profiles.calls == 0, "the file IS the attack — no confirmation needed"
