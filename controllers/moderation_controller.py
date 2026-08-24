"""The Controller: turns Telegram updates into domain calls.

It decides nothing and renders nothing. Its whole job is translation — pull the
few facts the Model needs out of an Update object, hand them over, and stop.
Everything Telegram-shaped stops here: knowing that a message can carry its
words in `caption` instead of `text`, that an edit arrives as `edited_message`,
that a file might be a `video_note` — none of that belongs in the Model, and
none of it belongs in a View.

Because it holds no logic, there is very little here to test directly; the
behaviour lives in ModerationModel and Policy, where it can be tested without
Telegram at all.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from models import AdminCache
from models.moderation_model import (
    Attachment, IncomingMessage, JoiningMember, ModerationModel,
)

log = logging.getLogger("scamguard.controller")

# Every attachment kind that can carry a payload. A fake APK renamed to .mp4 is
# still a fake APK, so document-only screening left a gap.
MEDIA_FIELDS = ("document", "animation", "video", "audio", "voice", "video_note")


def attachment_of(msg) -> Attachment | None:
    """First attachment that declares a name or type.

    Telegram only guarantees the DECLARED name and mime, so a missing name is
    not evidence of anything — it just means there is less to go on.
    """
    for field in MEDIA_FIELDS:
        obj = getattr(msg, field, None)
        if obj is None:
            continue
        name = getattr(obj, "file_name", None) or ""
        mime = getattr(obj, "mime_type", None)
        if not name and not mime:
            continue
        return Attachment(name, mime, getattr(obj, "file_size", None))
    return None


class ModerationController:
    def __init__(
        self,
        model: ModerationModel,
        admin_cache: AdminCache | None = None,
        skip_group_admins: bool = True,
    ) -> None:
        self._model = model
        self._admins = admin_cache or AdminCache()
        self._skip_admins = skip_group_admins

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Text, captions and attachments — new messages and edits alike.

        These are deliberately not separate handlers: python-telegram-bot runs
        only the first matching handler in a group, so a photo carrying both a
        scam caption and a fake .apk would be judged on one and never the other.
        """
        msg = update.effective_message
        user = update.effective_user
        if not msg or not user or user.is_bot:
            return

        # Anonymous admins and channel posts arrive with sender_chat set and a
        # placeholder from_user; there is no user to judge or act on.
        if getattr(msg, "sender_chat", None) is not None:
            return

        # Group admins cannot be deleted or banned by a bot, so moderating them
        # only produces alerts nobody can action. Checked before anything else
        # so a skipped admin costs no LLM call. (Cached per chat.)
        if self._skip_admins and await self._admins.is_admin(
            context.bot, msg.chat_id, user.id
        ):
            return

        text = msg.text or msg.caption or ""
        await self._model.judge(IncomingMessage(
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            user_id=user.id,
            username=user.username or "",
            chat_title=getattr(update.effective_chat, "title", "") or "",
            text=text,
            # Where the words came from matters to a reviewer: a caption and a
            # plain message read identically in an alert otherwise.
            via="caption" if (not msg.text and msg.caption) else "text",
            edited=bool(update.edited_message or update.edited_channel_post),
            attachment=attachment_of(msg),
        ))

    async def handle_new_members(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        msg = update.effective_message
        if not msg or not msg.new_chat_members:
            return
        for member in msg.new_chat_members:
            if member.is_bot:
                continue
            await self._model.screen_joiner(JoiningMember(
                chat_id=msg.chat_id,
                user_id=member.id,
                username=member.username or "",
            ))
