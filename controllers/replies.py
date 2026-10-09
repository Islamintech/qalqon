"""Answering a command without leaving litter in the group.

A reply to /stats or /help is for the admin who asked, not for every member
scrolling past later. In a group it is removed after a while; in private
chats and in the admin chat, where it is the record, it stays.
"""

GROUP_TYPES = ("group", "supergroup")


async def reply(update, text: str, *, view=None, admin_chat_id: str = "",
                ttl: float = 0, **kwargs):
    sent = await update.effective_message.reply_text(text, **kwargs)
    chat = update.effective_chat
    expire = getattr(view, "expire", None)
    if (
        ttl and expire and chat
        and getattr(chat, "type", "") in GROUP_TYPES
        and str(chat.id) != str(admin_chat_id or "")
    ):
        expire(chat.id, getattr(sent, "message_id", None), ttl)
    return sent
