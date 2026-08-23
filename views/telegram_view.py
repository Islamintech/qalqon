"""The View: every action the bot takes toward Telegram lives here, so the
controller never touches the Telegram API directly. Honors dry_run.

Alerts carry inline buttons. An alert an admin cannot act on is just noise —
the whole point of routing borderline cases to humans is that the human can
resolve them in one tap, from the same message.
"""
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from .alert_batcher import AlertBatcher

log = logging.getLogger("scamguard.view")

# callback_data is capped at 64 bytes by Telegram, so keep this format tight:
#   mod|<verb>|<chat_id>|<user_id>
CB_PREFIX = "mod"
VERB_BAN = "ban"
VERB_UNBAN = "unban"
VERB_IGNORE = "ok"
VERB_WHITELIST = "wl"


def build_callback(verb: str, chat_id: int, user_id: int) -> str:
    return f"{CB_PREFIX}|{verb}|{chat_id}|{user_id}"


def parse_callback(data: str) -> tuple[str, int, int] | None:
    try:
        prefix, verb, chat_id, user_id = data.split("|")
    except ValueError:
        return None
    if prefix != CB_PREFIX:
        return None
    try:
        return verb, int(chat_id), int(user_id)
    except ValueError:
        return None


def _keyboard(chat_id: int, user_id: int, banned: bool) -> InlineKeyboardMarkup:
    if banned:
        row = [
            InlineKeyboardButton(
                "♻️ Unban", callback_data=build_callback(VERB_UNBAN, chat_id, user_id)
            ),
            InlineKeyboardButton(
                "✅ Whitelist",
                callback_data=build_callback(VERB_WHITELIST, chat_id, user_id),
            ),
        ]
    else:
        row = [
            InlineKeyboardButton(
                "🚫 Ban", callback_data=build_callback(VERB_BAN, chat_id, user_id)
            ),
            InlineKeyboardButton(
                "👌 Ignore", callback_data=build_callback(VERB_IGNORE, chat_id, user_id)
            ),
            InlineKeyboardButton(
                "✅ Whitelist",
                callback_data=build_callback(VERB_WHITELIST, chat_id, user_id),
            ),
        ]
    return InlineKeyboardMarkup([row])


class TelegramView:
    def __init__(
        self,
        dry_run: bool,
        admin_chat_id: str = "",
        batcher: AlertBatcher | None = None,
    ) -> None:
        self._dry_run = dry_run
        self._admin_chat_id = admin_chat_id
        # Coalesces alerts when they arrive faster than a human can read them.
        self._batcher = batcher or AlertBatcher()

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def set_dry_run(self, value: bool) -> None:
        """Flipped at runtime by /dryrun so an admin can go live (or pull the
        handbrake) without a restart."""
        self._dry_run = value

    async def delete_message(self, bot: Bot, chat_id: int, message_id: int) -> bool:
        if self._dry_run:
            log.info("[dry-run] would delete message %s in %s", message_id, chat_id)
            return True
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except Exception as exc:
            log.warning("delete failed: %s", exc)
            return False

    async def kick_user(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        if self._dry_run:
            log.info("[dry-run] would ban user %s from %s", user_id, chat_id)
            return True
        try:
            # ban_chat_member removes and blocks re-join. Use unban afterwards
            # with only_if_banned if you'd rather just remove ("kick").
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            return True
        except Exception as exc:
            log.warning("ban failed: %s", exc)
            return False

    async def unban_user(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        if self._dry_run:
            log.info("[dry-run] would unban user %s in %s", user_id, chat_id)
            return True
        try:
            await bot.unban_chat_member(
                chat_id=chat_id, user_id=user_id, only_if_banned=True
            )
            return True
        except Exception as exc:
            log.warning("unban failed: %s", exc)
            return False

    async def report_to_admins(
        self,
        bot: Bot,
        text: str,
        chat_id: int | None = None,
        user_id: int | None = None,
        banned: bool = False,
    ) -> None:
        """Send an alert. When chat_id/user_id are given the alert gets action
        buttons; without an ADMIN_CHAT_ID it degrades to a log line.

        Under heavy load alerts are folded into a periodic digest instead — see
        AlertBatcher for why individually-actionable alerts stop being useful
        once there are thirty of them.
        """
        if self._dry_run:
            text = f"[DRY-RUN] {text}"
        if not self._admin_chat_id:
            log.info("ADMIN ALERT: %s", text)
            return

        async def _send(body: str) -> None:
            try:
                await bot.send_message(chat_id=self._admin_chat_id, text=body)
            except Exception as exc:
                log.warning("admin digest failed: %s", exc)

        summary = text.replace("\n", " | ")[:200]
        if not await self._batcher.submit(summary, _send):
            return  # folded into the next digest

        markup = (
            _keyboard(chat_id, user_id, banned)
            if chat_id is not None and user_id is not None
            else None
        )
        try:
            await bot.send_message(
                chat_id=self._admin_chat_id, text=text, reply_markup=markup
            )
        except Exception as exc:
            log.warning("admin report failed: %s", exc)

    async def flush_alerts(self, bot: Bot) -> None:
        """Emit any pending digest — called at shutdown so a raid's last alerts
        are not lost."""
        if not self._admin_chat_id:
            return

        async def _send(body: str) -> None:
            try:
                await bot.send_message(chat_id=self._admin_chat_id, text=body)
            except Exception as exc:
                log.warning("final digest failed: %s", exc)

        await self._batcher.flush(_send)
        await self._batcher.close()
