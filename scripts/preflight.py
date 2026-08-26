"""Pre-flight check. Run this BEFORE trusting the bot in a real group.

    python scripts/preflight.py                 # credentials only
    python scripts/preflight.py -1001234567890  # also check a specific group

Everything else in this project is tested against fakes, which cannot tell you
whether your token is valid, whether the bot was actually promoted to admin, or
whether Telegram will let it delete anything. That is exactly the class of
problem that only shows up in production, so this script goes and asks.

It is read-only apart from one optional test message to the admin chat, and it
never deletes or bans anything.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402

OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "
_results: list[tuple[str, str]] = []


def record(status: str, message: str) -> None:
    _results.append((status, message))
    print(f"[{status}] {message}")


async def check_telegram(chat_id: int | None) -> None:
    from telegram import Bot
    from telegram.error import TelegramError

    try:
        bot = Bot(settings.telegram_token)
        me = await bot.get_me()
        record(OK, f"bot token valid — @{me.username} (id {me.id})")
    except TelegramError as exc:
        record(FAIL, f"bot token rejected by Telegram: {exc}")
        return

    # Privacy mode decides whether the bot SEES ordinary group messages at all.
    # A bot with privacy mode on only receives commands and replies, so it would
    # sit there silently moderating nothing.
    if getattr(me, "can_read_all_group_messages", False):
        record(OK, "privacy mode is off — the bot can see all group messages")
    else:
        record(
            FAIL,
            "privacy mode is ON: the bot only sees commands, not ordinary "
            "messages, so it cannot moderate. Fix in @BotFather: "
            "/setprivacy -> your bot -> Disable, then re-add it to the group.",
        )

    if settings.admin_chat_id:
        try:
            await bot.send_message(
                chat_id=settings.admin_chat_id,
                text="✅ Qalqon preflight: alerts will arrive here.",
            )
            record(OK, f"admin chat {settings.admin_chat_id} reachable")
        except TelegramError as exc:
            record(
                FAIL,
                f"cannot post to ADMIN_CHAT_ID={settings.admin_chat_id}: {exc}. "
                "Alerts would be lost — add the bot to that chat.",
            )
    else:
        record(
            WARN,
            "ADMIN_CHAT_ID is empty — alerts only go to the log, and the "
            "inline Ban/Ignore buttons never reach a human",
        )

    if chat_id is None:
        record(
            WARN,
            "no group id given — pass one to verify admin rights: "
            "python scripts/preflight.py <chat_id>",
        )
        return

    try:
        chat = await bot.get_chat(chat_id)
        record(OK, f"group reachable — {chat.title or chat_id}")
    except TelegramError as exc:
        record(FAIL, f"cannot see chat {chat_id}: {exc}. Is the bot a member?")
        return

    try:
        member = await bot.get_chat_member(chat_id, me.id)
    except TelegramError as exc:
        record(FAIL, f"cannot read own membership in {chat_id}: {exc}")
        return

    if member.status != "administrator":
        record(
            FAIL,
            f"bot is '{member.status}', not an administrator — it cannot "
            "delete messages or remove anyone. Promote it in group settings.",
        )
        return
    record(OK, "bot is an administrator in the group")

    for attr, label, why in (
        ("can_delete_messages", "delete messages", "scam messages would stay up"),
        ("can_restrict_members", "ban users", "scammers could not be removed"),
    ):
        if getattr(member, attr, False):
            record(OK, f"permission: {label}")
        else:
            record(FAIL, f"missing permission: {label} — {why}")


async def check_groq() -> None:
    from models import LLMClient

    client = LLMClient(settings.groq_api_key, settings.groq_model, cache_ttl=0)
    verdict = await client.analyze("hello everyone, nice to be here")
    if verdict.degraded:
        record(FAIL, f"Groq unreachable: {verdict.reason}")
        return
    record(OK, f"Groq responding — model '{settings.groq_model}' returned "
               f"{verdict.risk.value} for a benign message")
    if verdict.risk.value != "CLEAN":
        record(
            WARN,
            "a plainly benign message did not come back CLEAN — the model or "
            "prompt may need tuning before going live",
        )


def _test_png(w: int = 64, h: int = 64) -> bytes:
    """A genuinely valid PNG, built here rather than hard-coded — a malformed
    stub gets rejected by the classifier ("broken PNG file") and would look
    exactly like a broken endpoint."""
    import struct
    import zlib

    raw = b"".join(bytes([0]) + bytes([120, 90, 70]) * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    signature = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A])
    return (
        signature
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


async def check_optional() -> None:
    if settings.hf_token:
        from models import VisionClient

        # Actually classify something. Checking the token alone would not have
        # caught the dead api-inference host, which failed DNS on every call.
        vision = VisionClient(settings.hf_token, nsfw_threshold=settings.nsfw_threshold)
        verdict = await vision.classify_image(_test_png())
        if verdict.degraded:
            record(
                FAIL,
                f"photo screening is configured but BROKEN: {verdict.reason}. "
                "HF_TOKEN must be a fine-grained token with the 'Make calls to "
                "Inference Providers' permission.",
            )
        else:
            record(OK, f"photo screening works — {verdict.reason}")
    else:
        record(WARN, "HF_TOKEN empty — profile-photo screening is off (optional)")

    if settings.mtproto_api_id and settings.mtproto_api_hash:
        session = f"{settings.mtproto_session}.session"
        if os.path.exists(session):
            record(OK, f"MTProto session file present ({session})")
        else:
            record(
                WARN,
                f"MTProto configured but {session} is missing — run "
                "`python scripts/telethon_login.py` once, or deep channel "
                "scanning stays off",
            )
    else:
        record(WARN, "MTProto not configured — deep channel scanning off (optional)")


async def main() -> None:
    chat_id = None
    if len(sys.argv) > 1:
        try:
            chat_id = int(sys.argv[1])
        except ValueError:
            print(f"not a chat id: {sys.argv[1]}")
            raise SystemExit(2)

    print("Qalqon preflight\n" + "=" * 60)
    try:
        settings.validate()
        record(OK, "required environment variables present")
    except RuntimeError as exc:
        record(FAIL, str(exc))
        print("\nCannot continue without credentials. Fill in .env first.")
        raise SystemExit(1)

    await check_telegram(chat_id)
    await check_groq()
    await check_optional()

    print("=" * 60)
    failures = [m for status, m in _results if status == FAIL]
    warnings = [m for status, m in _results if status == WARN]
    print(f"{len(_results)} checks — {len(failures)} failed, {len(warnings)} warnings")

    mode = "DRY-RUN" if settings.dry_run else "LIVE — real deletes and bans"
    print(f"mode: {mode}")
    if not settings.dry_run:
        print(
            "\n⚠️  DRY_RUN is off. Run with DRY_RUN=true for a few days first and "
            "read the logs — day-one auto-banning catches innocent people."
        )
    if failures:
        print("\nBlocking problems:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("\nAll clear.")


if __name__ == "__main__":
    asyncio.run(main())
