"""Admin surface: the inline buttons on every alert, plus slash commands.

Authorization is checked on EVERY entry point. The bot holds ban rights in the
group, so an unguarded /ban would hand that power to anyone who can type. Two
ways to qualify:
  - the command came from the configured ADMIN_CHAT_ID, or
  - the caller is a real admin/owner of the group in question (asked live)
"""
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from models.store import (
    Store, STATUS_BANNED, STATUS_NORMAL, STATUS_WHITELISTED,
)
from views import TelegramView
from views.telegram_view import (
    parse_callback, VERB_BAN, VERB_UNBAN, VERB_IGNORE, VERB_WHITELIST,
)

log = logging.getLogger("scamguard.admin")

HELP = """ScamGuard admin commands

/stats                     — totals for this chat
/status <user_id>          — one user's record and recent events
/whitelist <user_id>       — trust a user, clears their strikes
/unwhitelist <user_id>     — remove that trust
/forgive <user_id>         — clear active strikes (lifetime total is kept)
/unban <user_id>           — lift a ban this bot applied
/dryrun [on|off]           — show or flip the safety switch
/digest                    — send the pending digest right now
/help                      — this message

In the group, run these as a reply to the user's message to skip the id.
From the admin chat, pass the chat first: /status <chat_id> <user_id>"""


class AdminController:
    def __init__(
        self, store: Store, view: TelegramView, admin_chat_id: str = "",
        digest=None,
    ) -> None:
        self._store = store
        self._view = view
        self._admin_chat_id = str(admin_chat_id or "")
        self._digest = digest

    # --- authorization ---------------------------------------------------
    async def _is_admin(self, update: Update, context, chat_id: int | None = None) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        if not user:
            return False
        if self._admin_chat_id and chat and str(chat.id) == self._admin_chat_id:
            return True
        target = chat_id if chat_id is not None else (chat.id if chat else None)
        if target is None:
            return False
        try:
            member = await context.bot.get_chat_member(target, user.id)
            return member.status in ("administrator", "creator")
        except Exception as exc:
            log.warning("admin check failed for %s in %s: %s", user.id, target, exc)
            return False

    # --- argument parsing ------------------------------------------------
    def _targets(self, update: Update, context) -> tuple[int, int] | None:
        """Resolve (chat_id, user_id) from a reply, or from explicit args.
        In a group: /cmd <user_id> or a reply. In the admin chat, where there is
        no group context: /cmd <chat_id> <user_id>."""
        msg = update.effective_message
        chat = update.effective_chat
        args = context.args or []
        in_admin_chat = bool(
            self._admin_chat_id and chat and str(chat.id) == self._admin_chat_id
        )

        if msg and msg.reply_to_message and msg.reply_to_message.from_user:
            return msg.chat_id, msg.reply_to_message.from_user.id
        try:
            if len(args) >= 2:
                return int(args[0]), int(args[1])
            if len(args) == 1 and not in_admin_chat and chat:
                return chat.id, int(args[0])
        except ValueError:
            return None
        return None

    # --- commands --------------------------------------------------------
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_admin(update, context):
            return
        await update.effective_message.reply_text(HELP)

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_admin(update, context):
            return
        chat = update.effective_chat
        scope = None if str(chat.id) == self._admin_chat_id else chat.id
        s = await self._store.stats(scope)
        actions = ", ".join(f"{k}={v}" for k, v in sorted(s["actions"].items())) or "none"
        decay = f"{self._store.decay_days}d" if self._store.decay_days else "never"
        await update.effective_message.reply_text(
            f"📊 ScamGuard — {'all chats' if scope is None else f'chat {scope}'}\n"
            f"known users: {s['users']}\n"
            f"with active strikes: {s['users_with_strikes']} "
            f"({s['active_strikes']} strikes total)\n"
            f"whitelisted: {s['whitelisted']}\n"
            f"events: {s['events']} ({actions})\n"
            f"strike decay: {decay}\n"
            f"mode: {'DRY-RUN' if self._view.dry_run else 'LIVE'}"
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        target = self._targets(update, context)
        if not target:
            await update.effective_message.reply_text(
                "usage: /status <user_id> (or reply to their message)"
            )
            return
        chat_id, user_id = target
        if not await self._is_admin(update, context, chat_id):
            return
        rec = await self._store.get(chat_id, user_id)
        events = await self._store.recent_events(chat_id, user_id, limit=5)
        strikes = f"strikes: {rec.strikes} active"
        if rec.lifetime_strikes != rec.strikes:
            strikes += f" / {rec.lifetime_strikes} lifetime"
        expires = rec.strikes_expire_at(self._store.decay_days)
        if expires:
            days = max((expires - time.time()) / 86400.0, 0)
            strikes += f" (oldest expires in {days:.1f}d)"
        lines = [
            f"👤 user {user_id} (@{rec.username or '?'}) in {chat_id}",
            f"messages seen: {rec.messages_seen}",
            strikes,
            f"status: {rec.status}",
        ]
        if events:
            lines.append("recent:")
            lines += [f"  {e['action']} [{e['risk']}] {e['reason'][:80]}" for e in events]
        else:
            lines.append("recent: nothing on file")
        await update.effective_message.reply_text("\n".join(lines))

    async def whitelist(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._set_status_cmd(update, context, STATUS_WHITELISTED, "whitelisted ✅")

    async def unwhitelist(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._set_status_cmd(update, context, STATUS_NORMAL, "back to normal")

    async def forgive(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        target = self._targets(update, context)
        if not target:
            await update.effective_message.reply_text("usage: /forgive <user_id>")
            return
        chat_id, user_id = target
        if not await self._is_admin(update, context, chat_id):
            return
        await self._store.clear_strikes(chat_id, user_id)
        await update.effective_message.reply_text(f"strikes cleared for {user_id}")

    async def unban(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        target = self._targets(update, context)
        if not target:
            await update.effective_message.reply_text("usage: /unban <user_id>")
            return
        chat_id, user_id = target
        if not await self._is_admin(update, context, chat_id):
            return
        ok = await self._view.unban_user(context.bot, chat_id, user_id)
        await self._store.set_status(chat_id, user_id, STATUS_NORMAL)
        await self._store.clear_strikes(chat_id, user_id)
        await update.effective_message.reply_text(
            f"{'unbanned' if ok else 'unban failed for'} {user_id}"
        )

    async def dryrun(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_admin(update, context):
            return
        args = context.args or []
        if not args:
            await update.effective_message.reply_text(
                f"mode: {'DRY-RUN (no deletes/bans)' if self._view.dry_run else 'LIVE'}"
            )
            return
        want = args[0].lower()
        if want not in ("on", "off"):
            await update.effective_message.reply_text("usage: /dryrun on|off")
            return
        self._view.set_dry_run(want == "on")
        log.warning("dry_run set to %s by user %s", self._view.dry_run, update.effective_user.id)
        await update.effective_message.reply_text(
            f"mode is now {'DRY-RUN' if self._view.dry_run else '⚠️ LIVE — real bans'}"
        )

    async def digest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Flush the pending digest on demand, instead of waiting for the timer."""
        if not await self._is_admin(update, context):
            return
        if self._digest is None:
            await update.effective_message.reply_text("digests are not enabled")
            return
        pending = self._digest.pending
        if not pending:
            await update.effective_message.reply_text(
                "nothing pending — no automatic actions since the last digest"
            )
            return

        async def _send(body: str) -> None:
            await update.effective_message.reply_text(body)

        await self._digest.flush(_send)

    async def _set_status_cmd(self, update, context, status: str, label: str) -> None:
        target = self._targets(update, context)
        if not target:
            await update.effective_message.reply_text("usage: <command> <user_id>")
            return
        chat_id, user_id = target
        if not await self._is_admin(update, context, chat_id):
            return
        await self._store.set_status(chat_id, user_id, status)
        await update.effective_message.reply_text(f"user {user_id}: {label}")

    # --- inline buttons --------------------------------------------------
    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        parsed = parse_callback(query.data)
        if not parsed:
            await query.answer("unrecognized button")
            return
        verb, chat_id, user_id = parsed

        if not await self._is_admin(update, context, chat_id):
            await query.answer("not authorized", show_alert=True)
            return

        bot = context.bot
        if verb == VERB_BAN:
            await self._view.kick_user(bot, chat_id, user_id)
            await self._store.set_status(chat_id, user_id, STATUS_BANNED)
            note = "banned 🚫"
        elif verb == VERB_UNBAN:
            await self._view.unban_user(bot, chat_id, user_id)
            await self._store.set_status(chat_id, user_id, STATUS_NORMAL)
            await self._store.clear_strikes(chat_id, user_id)
            note = "unbanned ♻️"
        elif verb == VERB_IGNORE:
            # A false positive shouldn't leave a strike behind to escalate on.
            await self._store.clear_strikes(chat_id, user_id)
            note = "ignored — strikes cleared 👌"
        elif verb == VERB_WHITELIST:
            await self._store.set_status(chat_id, user_id, STATUS_WHITELISTED)
            note = "whitelisted ✅"
        else:
            await query.answer("unknown action")
            return

        by = update.effective_user
        await query.answer(note)
        try:
            # Stamp the outcome onto the alert and drop the buttons, so the same
            # case can't be resolved twice by two admins.
            await query.edit_message_text(
                f"{query.message.text}\n\n— {note} by @{by.username or by.id}"
            )
        except Exception as exc:
            log.warning("could not update alert message: %s", exc)
        log.info("admin %s -> %s on user %s in %s", by.id, verb, user_id, chat_id)
