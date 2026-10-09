"""The View: renders what the Model announces, into Telegram.

It SUBSCRIBES to the Model and reacts to events. The Controller never calls it,
and the Model never knows it exists — which is what makes this MVC rather than
three folders with MVC names. Adding another output channel (a webhook, an
email digest, a metrics exporter) means writing another subscriber, and neither
the Controller nor the Model changes.

This is also the only module that touches the Telegram API, so `dry_run` is
enforced in exactly one place: nothing else in the system is able to delete or
ban even by accident.

Alerts carry inline buttons because an alert an admin cannot act on is noise —
the point of routing a borderline case to a human is that the human can resolve
it in one tap. Resolving edits the message and drops the buttons so two admins
cannot action the same case twice.
"""
import asyncio
import logging
import time

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from models.events import (
    CaseResolved, DetectorDegraded, MemberJoined, MessageJudged, RaidDetected,
)
from models.verdict import Action

from .alert_batcher import AlertBatcher

log = logging.getLogger("qalqon.view")

# callback_data is capped at 64 bytes by Telegram, so keep this format tight:
#   mod|<verb>|<chat_id>|<user_id>
CB_PREFIX = "mod"
VERB_BAN = "ban"
VERB_UNBAN = "unban"
VERB_IGNORE = "ok"
VERB_WHITELIST = "wl"

_ICON = {
    Action.NONE: "",
    Action.REVIEW: "⚠️ Review",
    Action.DELETE: "🧹 Deleted",
    Action.BAN: "🚫 Removed",
}

# What the GROUP is told, by the signal that decided it — (Uzbek, English).
# A category, never the detector's own reason: spelling out exactly what
# tripped the filter is a how-to for the next attempt.
_PUBLIC_REASON = {
    "link": ("shubhali havola", "suspicious link"),
    "file": ("xavfli fayl", "dangerous file"),
    "keyword": ("firibgarlik belgilari", "signs of a scam"),
    "llm": ("firibgarlik belgilari", "signs of a scam"),
    "burst": ("ketma-ket ko'p xabar", "message flooding"),
}
_PUBLIC_REASON_DEFAULT = ("shubhali xabar", "suspicious message")

# Telegram allows a bot about 20 messages a minute in one group. A raid can
# produce more removals than that, and a notice must never be what gets the
# bot rate-limited in the middle of cleaning up — so at most one per gap.
NOTICE_GAP = 3.0


def group_notice(action: Action, source: str) -> str:
    """The note left in the group after a removal. No username: scam accounts
    often ARE the advert (@crypto_profit_xx), and naming one repeats it."""
    uz, en = _PUBLIC_REASON.get(source, _PUBLIC_REASON_DEFAULT)
    if action.bans:
        return (
            f"🚫 Foydalanuvchi guruhdan chiqarildi.\nSabab: {uz}\n\n"
            f"🚫 A user was removed from the group.\nReason: {en}"
        )
    return (
        f"🧹 Xabar o'chirildi.\nSabab: {uz}\n\n"
        f"🧹 A message was removed.\nReason: {en}"
    )


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
        digest=None,
        autonomy=None,
        notice_ttl: float = 0,
        clock=time.monotonic,
    ) -> None:
        self._dry_run = dry_run
        self._admin_chat_id = admin_chat_id
        self._batcher = batcher or AlertBatcher()
        self._digest = digest
        self._autonomy = autonomy
        self._bot: Bot | None = None
        # Seconds a removal notice stays in the group; 0 posts none.
        self._notice_ttl = notice_ttl
        self._clock = clock
        self._last_notice: dict[int, float] = {}
        # Bot messages still waiting to be cleaned up (notices and command
        # replies), so shutdown can do it now instead of leaving them for good.
        self._notices: dict[tuple[int, int], asyncio.Task] = {}

    # --- lifecycle ---------------------------------------------------------
    def attach(self, bot: Bot) -> None:
        """Handed the Bot once at startup, so no method needs it threaded
        through as an argument — and so the Model never has to hold one."""
        self._bot = bot

    def subscribe_to(self, model) -> None:
        model.subscribe(self.on_event)

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def set_dry_run(self, value: bool) -> None:
        """Flipped at runtime by /dryrun so an admin can go live — or pull the
        handbrake — without a restart."""
        self._dry_run = value

    # --- the observer entry point -----------------------------------------
    async def on_event(self, event) -> None:
        if isinstance(event, MessageJudged):
            await self._on_judged(event)
        elif isinstance(event, DetectorDegraded):
            await self._on_degraded(event)
        elif isinstance(event, RaidDetected):
            await self._on_raid(event)
        elif isinstance(event, MemberJoined):
            await self._on_joined(event)
        elif isinstance(event, CaseResolved):
            log.info(
                "admin %s -> %s on user %s in %s",
                event.by_user_id, event.verb, event.user_id, event.chat_id,
            )

    async def _on_judged(self, e: MessageJudged) -> None:
        removed = banned = False
        if e.action.deletes:
            removed = await self.delete_message(e.chat_id, e.message_id)
        if e.action.bans:
            banned = await self.kick_user(e.chat_id, e.user_id)
        # Only for what really happened: a dry run or a failed delete leaves
        # the message up, and a notice saying otherwise would be a lie.
        if (removed or banned) and not self._dry_run:
            await self.post_notice(e.chat_id, e.action, e.content.source)

        live = self._autonomy is None or self._autonomy.alerts_live(e.action)
        if live or self._digest is None:
            await self.report_to_admins(
                f"{_ICON[e.action]}\n{e.summary}",
                chat_id=e.chat_id, user_id=e.user_id, banned=e.action.bans,
            )
        else:
            # Already handled and low-stakes: fold it into the next digest
            # rather than pinging a human per removed spam line. With no digest
            # configured we alert anyway — never drop a finding silently.
            await self._digest.add(
                e.chat_id, e.chat_title, e.action.value, e.username,
                e.user_id, e.reason,
            )

    async def _on_degraded(self, e: DetectorDegraded) -> None:
        still_working = {
            "language model": "Keyword, link and file checks still run",
            "photo screening": "Text, link and file checks still run",
        }.get(e.subsystem, "Other checks still run")
        await self.report_to_admins(
            f"⚠️ Qalqon {e.subsystem} is DEGRADED\n"
            f"Unreachable: {e.reason[:200]}\n"
            f"{still_working}, but this signal is missing until it recovers. "
            "Nothing is being auto-banned on its behalf."
        )

    async def _on_raid(self, e: RaidDetected) -> None:
        await self.report_to_admins(
            f"🌊 Possible raid in {e.chat_id}: {e.accounts} new accounts "
            "posting in the last minute. Alerts will be batched while this "
            "lasts. Nothing is being auto-banned on pace alone."
        )

    async def _on_joined(self, e: MemberJoined) -> None:
        await self.report_to_admins(
            f"👤 Joined — user={e.user_id} (@{e.username}) "
            f"profile={e.profile.risk.value}: {e.profile.reason}",
            chat_id=e.chat_id, user_id=e.user_id,
        )

    # --- actions -----------------------------------------------------------
    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        if self._dry_run:
            log.info("[dry-run] would delete message %s in %s", message_id, chat_id)
            return True
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except Exception as exc:
            log.warning("delete failed: %s", exc)
            return False

    async def kick_user(self, chat_id: int, user_id: int) -> bool:
        if self._dry_run:
            log.info("[dry-run] would ban user %s from %s", user_id, chat_id)
            return True
        try:
            # ban_chat_member removes and blocks re-join. Use unban afterwards
            # with only_if_banned if you'd rather just remove ("kick").
            await self._bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            return True
        except Exception as exc:
            log.warning("ban failed: %s", exc)
            return False

    async def post_notice(self, chat_id: int, action: Action, source: str) -> None:
        """Tell the group why something vanished, then tidy the note away."""
        if not self._notice_ttl:
            return
        now = self._clock()
        if now - self._last_notice.get(chat_id, float("-inf")) < NOTICE_GAP:
            return
        self._last_notice[chat_id] = now
        try:
            sent = await self._bot.send_message(
                chat_id=chat_id, text=group_notice(action, source)
            )
        except Exception as exc:
            log.warning("group notice failed: %s", exc)
            return
        self.expire(chat_id, getattr(sent, "message_id", None), self._notice_ttl)

    def expire(self, chat_id: int, message_id: int | None, ttl: float) -> None:
        """Delete one of the bot's OWN messages after `ttl` seconds.

        Housekeeping, not moderation, so dry-run does not hold it back: the
        bot tidying up after itself changes nothing about anyone's standing.
        """
        if message_id is None or not ttl:
            return

        async def _expire() -> None:
            try:
                await asyncio.sleep(ttl)
                await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("could not remove bot message: %s", exc)
            finally:
                self._notices.pop((chat_id, message_id), None)

        self._notices[(chat_id, message_id)] = asyncio.create_task(_expire())

    async def remove_service_message(self, chat_id: int, message_id: int) -> bool:
        """Delete a service line such as "X added Qalqon". Like expire(), this
        is housekeeping, so it runs in dry-run too."""
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except Exception as exc:
            # Usual cause: added before being promoted, so no delete right yet.
            log.info("could not remove service message in %s: %s", chat_id, exc)
            return False

    async def leave_chat(self, chat_id: int) -> bool:
        """Take the bot out of a group. Not moderation, so not dry-run gated."""
        try:
            await self._bot.leave_chat(chat_id=chat_id)
            return True
        except Exception as exc:
            log.warning("leave failed for %s: %s", chat_id, exc)
            return False

    async def clear_notices(self) -> None:
        """At shutdown: remove pending bot messages now. Their timers die with
        the process, and a message nobody removes stays in the group for good."""
        pending, self._notices = self._notices, {}
        for (chat_id, message_id), task in pending.items():
            task.cancel()
            try:
                await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as exc:
                log.warning("could not remove group notice: %s", exc)

    async def unban_user(self, chat_id: int, user_id: int) -> bool:
        if self._dry_run:
            log.info("[dry-run] would unban user %s in %s", user_id, chat_id)
            return True
        try:
            await self._bot.unban_chat_member(
                chat_id=chat_id, user_id=user_id, only_if_banned=True
            )
            return True
        except Exception as exc:
            log.warning("unban failed: %s", exc)
            return False

    async def report_to_admins(
        self,
        text: str,
        chat_id: int | None = None,
        user_id: int | None = None,
        banned: bool = False,
    ) -> None:
        """Send an alert. With chat_id/user_id it gets action buttons; without
        an ADMIN_CHAT_ID it degrades to a log line.

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
                await self._bot.send_message(chat_id=self._admin_chat_id, text=body)
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
            await self._bot.send_message(
                chat_id=self._admin_chat_id, text=text, reply_markup=markup
            )
        except Exception as exc:
            log.warning("admin report failed: %s", exc)

    async def flush_alerts(self) -> None:
        """Emit any pending digest — called at shutdown so a raid's last alerts
        are not lost."""
        if not self._admin_chat_id:
            return

        async def _send(body: str) -> None:
            try:
                await self._bot.send_message(chat_id=self._admin_chat_id, text=body)
            except Exception as exc:
                log.warning("final digest failed: %s", exc)

        await self._batcher.flush(_send)
        await self._batcher.close()
