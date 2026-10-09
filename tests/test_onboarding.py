"""The install path.

Weighted toward the ways a setup can be silently broken, because that is the
failure this surface exists to prevent: a bot that was added but cannot act
looks exactly like a bot with nothing to do.
"""
import pytest

from controllers.onboarding_controller import OnboardingController, invite_markup
from tests.conftest import FakeBot, FakeContext, FakeMessage, FakeUpdate, FakeUser


class FakeView:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run


def _private(bot):
    msg = FakeMessage(text="/start", chat_id=555)
    return msg, FakeUpdate(msg, chat_id=555, chat_type="private"), FakeContext(bot)


def _group(bot, title="Crypto Signals"):
    msg = FakeMessage(text="/start", chat_id=-1001)
    return msg, FakeUpdate(msg, chat_id=-1001, chat_type="supergroup",
                           chat_title=title), FakeContext(bot)


# --- the private welcome ------------------------------------------------
@pytest.mark.asyncio
async def test_private_start_explains_the_two_rights():
    bot = FakeBot()
    msg, update, ctx = _private(bot)
    await OnboardingController(FakeView()).start(update, ctx)

    body = msg.replies[0]
    assert "delete messages" in body.lower()
    assert "ban users" in body.lower()


@pytest.mark.asyncio
async def test_add_button_requests_both_rights_in_the_invite():
    """The rights must be pre-ticked in the invite dialog itself. A separate
    'now go promote it' step is the one people skip."""
    markup = invite_markup("QalqonSafeBot")
    url = markup.inline_keyboard[0][0].url
    assert "startgroup=true" in url
    assert "admin=delete_messages+restrict_members" in url
    assert "t.me/QalqonSafeBot" in url


@pytest.mark.asyncio
async def test_private_start_carries_the_button():
    bot = FakeBot()
    msg, update, ctx = _private(bot)
    await OnboardingController(FakeView()).start(update, ctx)
    assert msg.markups[0] is not None


@pytest.mark.asyncio
async def test_missing_username_costs_the_button_not_the_message():
    bot = FakeBot()
    bot.username = ""
    msg, update, ctx = _private(bot)
    await OnboardingController(FakeView()).start(update, ctx)
    assert msg.replies, "the welcome text must still be sent"
    assert msg.markups[0] is None


def test_privacy_link_only_appears_when_a_url_is_configured():
    assert len(invite_markup("B").inline_keyboard) == 1
    assert len(invite_markup("B", "https://x/privacy").inline_keyboard) == 2


# --- the group diagnosis ------------------------------------------------
@pytest.mark.asyncio
async def test_group_start_reports_ready_when_fully_set_up():
    bot = FakeBot()
    msg, update, ctx = _group(bot)
    await OnboardingController(FakeView()).start(update, ctx)

    body = msg.replies[0]
    assert "Crypto Signals" in body
    assert "Ready" in body
    assert "❌" not in body


@pytest.mark.asyncio
async def test_not_an_administrator_is_reported_as_the_blocker():
    bot = FakeBot()
    bot.bot_is_admin = False
    msg, update, ctx = _group(bot)
    await OnboardingController(FakeView()).start(update, ctx)

    body = msg.replies[0]
    assert "Not an administrator" in body
    assert "Ready" not in body


@pytest.mark.asyncio
async def test_each_missing_right_names_what_it_costs():
    bot = FakeBot()
    bot.rights = {"can_delete_messages": False, "can_restrict_members": True}
    msg, update, ctx = _group(bot)
    await OnboardingController(FakeView()).start(update, ctx)

    body = msg.replies[0]
    assert "❌ Delete messages — scam posts would stay up" in body
    assert "✅ Ban users" in body
    assert "Ready" not in body


@pytest.mark.asyncio
async def test_privacy_mode_is_caught_even_though_rights_are_fine():
    """Its symptom is the bot doing nothing — which admins blame on rights."""
    bot = FakeBot()
    bot.privacy_off = False
    msg, update, ctx = _group(bot)
    await OnboardingController(FakeView()).start(update, ctx)

    body = msg.replies[0]
    assert "privacy mode is on" in body
    assert "@BotFather" in body
    assert "Ready" not in body


@pytest.mark.asyncio
async def test_dry_run_is_never_reported_as_simply_ready():
    """Fully permitted but changing nothing is not the same as protected."""
    bot = FakeBot()
    msg, update, ctx = _group(bot)
    await OnboardingController(FakeView(dry_run=True)).start(update, ctx)

    body = msg.replies[0]
    assert "dry-run" in body
    assert "/dryrun off" in body


@pytest.mark.asyncio
async def test_a_failed_rights_lookup_does_not_claim_the_group_is_ready():
    class Broken(FakeBot):
        async def get_chat_member(self, chat_id, user_id):
            raise RuntimeError("network")

    bot = Broken()
    msg, update, ctx = _group(bot)
    await OnboardingController(FakeView()).start(update, ctx)

    body = msg.replies[0]
    assert "could not read my own permissions" in body
    assert "Ready" not in body


# --- arriving in a group ------------------------------------------------
@pytest.mark.asyncio
async def test_setup_card_goes_to_the_admin_chat_not_the_group():
    bot = FakeBot()
    msg = FakeMessage(text="", chat_id=-1001)
    msg.new_chat_members = [FakeUser(user_id=bot.id, username="qalqon", is_bot=True)]
    update = FakeUpdate(msg, chat_id=-1001, chat_type="supergroup")
    await OnboardingController(FakeView(), admin_chat_id="999").on_added(
        update, FakeContext(bot)
    )

    assert msg.replies == [], "members should not see a setup checklist"
    [(chat, text, _)] = bot.sent
    assert chat == "999"
    assert "Qalqon setup" in text and "-1001" in text


@pytest.mark.asyncio
async def test_without_an_admin_chat_the_install_is_silent_in_the_group():
    bot = FakeBot()
    msg = FakeMessage(text="", chat_id=-1001)
    msg.new_chat_members = [FakeUser(user_id=bot.id, username="qalqon", is_bot=True)]
    update = FakeUpdate(msg, chat_id=-1001, chat_type="supergroup")
    await OnboardingController(FakeView()).on_added(update, FakeContext(bot))

    assert msg.replies == [] and bot.sent == []


@pytest.mark.asyncio
async def test_another_member_joining_is_not_an_install():
    bot = FakeBot()
    msg = FakeMessage(text="", chat_id=-1001)
    msg.new_chat_members = [FakeUser(user_id=4242, username="someone")]
    update = FakeUpdate(msg, chat_id=-1001, chat_type="supergroup")
    await OnboardingController(FakeView(), admin_chat_id="999").on_added(
        update, FakeContext(bot)
    )

    assert msg.replies == [] and bot.sent == []
