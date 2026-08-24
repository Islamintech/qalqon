"""Group admins are skipped: Telegram will not let a bot delete or ban them,
so moderating them only produces alerts nobody can act on."""
import pytest

from conftest import FakeContext, FakeLLM, FakeMessage, FakeProfiles, FakeUpdate, FakeUser
from models import AdminCache, Risk
from test_controller import build


class _Member:
    def __init__(self, uid):
        class U:
            id = uid
        self.user = U()


class AdminBot:
    """Counts calls so the caching claim is actually verified."""

    def __init__(self, admin_ids=(1,), fail=False):
        self._ids = admin_ids
        self._fail = fail
        self.calls = 0
        self.deleted, self.banned, self.sent, self.unbanned = [], [], [], []

    async def get_chat_administrators(self, chat_id):
        self.calls += 1
        if self._fail:
            raise RuntimeError("telegram is having a moment")
        return [_Member(i) for i in self._ids]

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


# --- the cache -------------------------------------------------------------
async def test_admins_are_fetched_once_per_chat():
    """One API call per chat per TTL, not one per message — otherwise every
    message in the group costs a round-trip."""
    bot, cache = AdminBot(admin_ids=(7, 8)), AdminCache(ttl=300)
    for _ in range(50):
        await cache.is_admin(bot, -100, 7)
    assert bot.calls == 1


async def test_the_cache_expires():
    bot, cache = AdminBot(admin_ids=(7,)), AdminCache(ttl=0)
    await cache.is_admin(bot, -100, 7)
    await cache.is_admin(bot, -100, 7)
    assert bot.calls == 2


async def test_chats_are_cached_separately():
    bot, cache = AdminBot(admin_ids=(7,)), AdminCache()
    await cache.is_admin(bot, -100, 7)
    await cache.is_admin(bot, -200, 7)
    assert bot.calls == 2


async def test_invalidate_forces_a_refetch():
    bot, cache = AdminBot(admin_ids=(7,)), AdminCache()
    await cache.is_admin(bot, -100, 7)
    cache.invalidate(-100)
    await cache.is_admin(bot, -100, 7)
    assert bot.calls == 2


async def test_a_failure_reports_not_admin_so_moderation_continues():
    """Failing the other way would silently switch moderation off for the whole
    group whenever Telegram hiccups."""
    bot, cache = AdminBot(fail=True), AdminCache()
    assert await cache.is_admin(bot, -100, 7) is False


async def test_a_failure_is_not_cached():
    """Otherwise one blip disables the exemption for the whole TTL."""
    bot, cache = AdminBot(admin_ids=(7,), fail=True), AdminCache(ttl=300)
    await cache.is_admin(bot, -100, 7)
    await cache.is_admin(bot, -100, 7)
    assert bot.calls == 2


async def test_non_admins_are_reported_as_such():
    bot, cache = AdminBot(admin_ids=(1, 2)), AdminCache()
    assert await cache.is_admin(bot, -100, 999) is False
    assert await cache.is_admin(bot, -100, 2) is True


# --- through the controller ------------------------------------------------
async def test_an_admin_posting_a_scam_is_skipped(store, bot):
    llm = FakeLLM(Risk.RED_FLAG)
    admin_bot = AdminBot(admin_ids=(100,))
    controller, _ = build(store, llm, FakeProfiles(Risk.RED_FLAG),
                          bot=admin_bot, skip_admins=True)
    msg = FakeMessage(text="guaranteed 300% returns, dm me now please")
    await controller.handle_message(FakeUpdate(msg), FakeContext(admin_bot))
    assert admin_bot.sent == [], "an alert about an admin is unactionable noise"
    assert llm.calls == [], "and it must not cost an LLM call either"


async def test_an_ordinary_member_is_still_moderated(store, bot):
    admin_bot = AdminBot(admin_ids=(999,))  # someone else is the admin
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG),
                          FakeProfiles(Risk.RED_FLAG),
                          bot=admin_bot, skip_admins=True)
    msg = FakeMessage(text="guaranteed 300% returns, dm me now please")
    await controller.handle_message(FakeUpdate(msg), FakeContext(admin_bot))
    assert admin_bot.deleted, "a normal member must still be acted on"


async def test_the_skip_can_be_switched_off(store):
    """Needed while testing with your own admin account."""
    admin_bot = AdminBot(admin_ids=(100,))
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG),
                          FakeProfiles(Risk.RED_FLAG), bot=admin_bot,
                          skip_admins=False)
    msg = FakeMessage(text="guaranteed 300% returns, dm me now please")
    await controller.handle_message(FakeUpdate(msg), FakeContext(admin_bot))
    assert admin_bot.banned, "with the skip off, admins are moderated again"


async def test_an_anonymous_admin_post_is_skipped(store, bot):
    """sender_chat means the group itself posted — there is no user to judge."""
    llm = FakeLLM(Risk.RED_FLAG)
    controller, _ = build(store, llm, FakeProfiles(Risk.RED_FLAG), bot=bot)
    msg = FakeMessage(text="guaranteed 300% returns, dm me now please")
    msg.sender_chat = object()
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert llm.calls == [] and bot.sent == []
