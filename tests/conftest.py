"""Test doubles. Nothing here touches the network or a real Telegram chat —
the whole point is that the escalation logic can be exercised exhaustively and
instantly."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Store, Verdict, Risk  # noqa: E402


@pytest.fixture
async def store(tmp_path):
    s = Store(str(tmp_path / f"{uuid.uuid4().hex}.db"))
    await s.start()
    yield s
    await s.stop()


class FakeBot:
    """Records what was asked of Telegram instead of calling it."""

    def __init__(self):
        self.deleted = []
        self.banned = []
        self.unbanned = []
        self.sent = []
        self.admins = set()

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=True):
        self.unbanned.append((chat_id, user_id))

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    async def get_chat_administrators(self, chat_id):
        # Mirrors the real Bot: the controller asks this for the admin skip.
        # `admins` is the set of user ids the test wants treated as admins.
        class _M:
            def __init__(self, uid):
                class U:
                    id = uid
                self.user = U()

        return [_M(uid) for uid in self.admins]

    async def get_chat_member(self, chat_id, user_id):
        class M:
            status = "administrator" if user_id in self.admins else "member"
        return M()


class FakeUser:
    def __init__(self, user_id=100, username="scammer", is_bot=False):
        self.id = user_id
        self.username = username
        self.is_bot = is_bot


class FakeMessage:
    """Mirrors the attribute surface the controller actually touches. Every
    media slot exists (as None) because a real telegram.Message always has
    them — a fake that omits one lets a test pass on a message shape that
    would crash in production."""

    MEDIA = ("document", "animation", "video", "audio", "voice", "video_note")

    def __init__(
        self, text="hi", chat_id=-1001, message_id=7, user=None,
        caption=None, **media,
    ):
        self.text = text
        self.caption = caption
        self.chat_id = chat_id
        self.message_id = message_id
        self.from_user = user or FakeUser()
        for attr in self.MEDIA:
            setattr(self, attr, media.get(attr))
        # A real Message always carries these; sender_chat is set for channel
        # posts and anonymous admins, where there is no user to judge.
        self.sender_chat = None
        self.new_chat_members = []
        self.reply_to_message = None
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


class FakeUpdate:
    def __init__(
        self, message=None, user=None, chat_id=-1001, callback_query=None,
        edited=False,
    ):
        self.effective_message = message
        self.effective_user = user or (message.from_user if message else None)
        self.callback_query = callback_query
        # A real Update always carries these; edited_message is set instead of
        # message when the user edits an existing post.
        self.edited_message = message if edited else None
        self.edited_channel_post = None
        self.message = None if edited else message

        class Chat:
            id = chat_id
        self.effective_chat = Chat()


class FakeContext:
    def __init__(self, bot, args=None):
        self.bot = bot
        self.args = args or []


class FakeLLM:
    """Stands in for Groq. Returns whatever verdict the test dictates."""

    def __init__(self, risk=Risk.CLEAN, reason="fake"):
        self.risk = risk
        self.reason = reason
        self.calls = []

    async def analyze(self, text, context=""):
        self.calls.append((text, context))
        return Verdict(self.risk, self.reason, "llm")


class FakeProfiles:
    """The profile port as the Model sees it: no Telegram object anywhere."""

    def __init__(self, risk=Risk.CLEAN, reason="fake profile"):
        self.risk = risk
        self.reason = reason
        self.calls = 0

    def attach(self, bot):
        pass

    async def analyze(self, user_id):
        self.calls += 1
        return Verdict(self.risk, self.reason, "profile")


@pytest.fixture
def bot():
    return FakeBot()
