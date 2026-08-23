"""Run ONCE, interactively, to create the user session the bot reuses.

    python scripts/telethon_login.py

You'll be asked for your phone number, the login code Telegram sends you, and
your 2FA password if you have one. It writes <session>.session to the project
root. After that the bot connects non-interactively.

Use a DEDICATED account — automating your personal account risks a ban.
"""
import asyncio
import os
import sys

# make the project root importable when run as `python scripts/telethon_login.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient  # noqa: E402

from config import settings  # noqa: E402


async def main() -> None:
    if not (settings.mtproto_api_id and settings.mtproto_api_hash):
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first")
    client = TelegramClient(
        settings.mtproto_session,
        int(settings.mtproto_api_id),
        settings.mtproto_api_hash,
    )
    await client.start()  # interactive: prompts for phone + code
    me = await client.get_me()
    print(f"Logged in as {me.username or me.id}. Session saved.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
