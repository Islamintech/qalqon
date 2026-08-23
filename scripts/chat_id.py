"""Find the chat IDs you need for .env.

    python scripts/chat_id.py

Then, while it is running, post any message in each chat you care about — your
moderated group, and the private group you want alerts in. Each one prints its
id as the message arrives. Ctrl-C when you have them.

Group ids are large negative numbers (-1001234567890); your own DM with the bot
is a positive number. Put the ALERT group's id in ADMIN_CHAT_ID, and pass the
MODERATED group's id to scripts/preflight.py.

This consumes pending updates, which is harmless before the bot is running —
but do not run it at the same time as main.py, or the two will compete for the
same update stream and each will see only some of the messages.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402


async def main() -> None:
    from telegram import Bot
    from telegram.error import TelegramError

    if not settings.telegram_token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first")

    bot = Bot(settings.telegram_token)
    try:
        me = await bot.get_me()
    except TelegramError as exc:
        raise SystemExit(f"Bot token rejected: {exc}")

    print(f"Listening as @{me.username}.")
    print("Post a message in each chat you want the id of. Ctrl-C to stop.\n")
    if not getattr(me, "can_read_all_group_messages", False):
        print(
            "NOTE: privacy mode is ON, so the bot only sees messages that are\n"
            "      commands or replies to it. Either send /start in the group,\n"
            "      or disable privacy mode in @BotFather (/setprivacy).\n"
        )

    seen: dict[int, str] = {}
    offset = None
    try:
        while True:
            updates = await bot.get_updates(offset=offset, timeout=30)
            for update in updates:
                offset = update.update_id + 1
                msg = update.effective_message
                if not msg:
                    continue
                chat = msg.chat
                if chat.id in seen:
                    continue
                label = chat.title or chat.full_name or chat.type
                seen[chat.id] = label
                kind = "group" if chat.id < 0 else "private chat"
                print(f"  {chat.id}   ({kind}: {label})")
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if seen:
            print("\nFound:")
            for chat_id, label in seen.items():
                print(f"  {chat_id}  {label}")
            print(
                "\nPut the ALERT chat in .env as   ADMIN_CHAT_ID=<id>\n"
                "Check the MODERATED group with   python scripts/preflight.py <id>"
            )
        else:
            print("\nNo messages seen. Did you post in the chat while this ran?")


if __name__ == "__main__":
    asyncio.run(main())
