"""The bot does not leave its own messages lying around in groups.

Command replies there are for the admin who asked, and the "X added Qalqon"
line is noise. The admin chat is the record, so nothing is removed there.
"""
import asyncio
from types import SimpleNamespace

from controllers.onboarding_controller import OnboardingController
from controllers.replies import reply
from tests.conftest import FakeBot, FakeContext, FakeMessage, FakeUpdate, FakeUser


class View:
    def __init__(self):
        self.expiring, self.removed = [], []
        self.dry_run = True

    def expire(self, chat_id, message_id, ttl):
        self.expiring.append((chat_id, message_id, ttl))

    async def remove_service_message(self, chat_id, message_id):
        self.removed.append((chat_id, message_id))
        return True


class Msg(FakeMessage):
    async def reply_text(self, text, **kw):
        await super().reply_text(text, **kw)
        return SimpleNamespace(message_id=77)


def update_in(chat_id, chat_type):
    msg = Msg(text="/stats", chat_id=chat_id)
    return FakeUpdate(msg, chat_id=chat_id, chat_type=chat_type)


async def test_a_reply_in_a_group_is_set_to_expire():
    view = View()
    await reply(update_in(-1001, "supergroup"), "hi", view=view, admin_chat_id="999", ttl=60)
    assert view.expiring == [(-1001, 77, 60)]


async def test_a_reply_in_the_admin_chat_stays():
    view = View()
    await reply(update_in(-999, "supergroup"), "hi", view=view, admin_chat_id="-999", ttl=60)
    assert view.expiring == []


async def test_a_reply_in_private_stays():
    view = View()
    await reply(update_in(555, "private"), "hi", view=view, admin_chat_id="999", ttl=60)
    assert view.expiring == []


async def test_ttl_zero_keeps_replies():
    view = View()
    await reply(update_in(-1001, "group"), "hi", view=view, ttl=0)
    assert view.expiring == []


async def test_the_added_line_is_removed_when_the_bot_joins():
    bot, view = FakeBot(), View()
    msg = FakeMessage(text="", chat_id=-1001)
    msg.message_id = 31
    msg.new_chat_members = [FakeUser(user_id=bot.id, username="qalqon", is_bot=True)]
    update = FakeUpdate(msg, chat_id=-1001, chat_type="supergroup")
    await OnboardingController(view, admin_chat_id="999").on_added(update, FakeContext(bot))
    assert view.removed == [(-1001, 31)]


async def test_view_expire_deletes_the_bot_message_after_the_ttl():
    from views import TelegramView

    bot = FakeBot()
    view = TelegramView(dry_run=True)
    view.attach(bot)
    view.expire(-1001, 88, 0.01)
    await asyncio.sleep(0.05)
    assert (-1001, 88) in bot.deleted, "housekeeping is not held back by dry run"
