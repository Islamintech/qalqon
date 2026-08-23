"""The Controller: gathers evidence, asks the Policy what to do, tells the View
to do it, and writes the outcome to the Store.

Flow per message (text, caption, attachment, new or edited — one entry point):
  1. store.touch      -> who is this? new account or established member?
  2. whitelist check  -> admin-vouched users skip the pipeline entirely
  3. keyword filter   -> cheap regex first pass
  4. Groq LLM         -> unless the message is too short to carry a pitch
  5. profile check    -> only for non-clean content
  6. policy.decide    -> NONE / REVIEW / DELETE / BAN, with strikes + trust
  7. act + record
"""
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from models import (
    KeywordFilter, LLMClient, ProfileAnalyzer, FileScanner, Verdict, Risk,
    Action, Policy, Store, LinkAnalyzer, BurstDetector, AdminCache,
    Autonomy, file_decision,
)
from models.store import STATUS_BANNED
from views import TelegramView

log = logging.getLogger("scamguard.controller")

# Below this length, a message with no link/mention/keyword hit is not worth an
# LLM call. Short group chatter ("ok", "thanks") is most of the traffic.
MIN_LLM_CHARS = 12

# How long to stay quiet after warning admins that the LLM is unreachable.
DEGRADED_WARN_COOLDOWN = 1800.0  # 30 minutes

_ICON = {
    Action.NONE: "",
    Action.REVIEW: "⚠️ Review",
    Action.DELETE: "🧹 Deleted",
    Action.BAN: "🚫 Removed",
}


class ModerationController:
    def __init__(
        self,
        keyword_filter: KeywordFilter,
        llm_client: LLMClient,
        profile_analyzer: ProfileAnalyzer,
        view: TelegramView,
        store: Store,
        policy: Policy,
        file_scanner: FileScanner | None = None,
        link_analyzer: LinkAnalyzer | None = None,
        burst_detector: BurstDetector | None = None,
        admin_cache: AdminCache | None = None,
        digest=None,
        autonomy: Autonomy = Autonomy.ASSISTED,
        skip_group_admins: bool = True,
        trust_after_messages: int = 25,
    ) -> None:
        self._keywords = keyword_filter
        self._llm = llm_client
        self._profiles = profile_analyzer
        self._view = view
        self._store = store
        self._policy = policy
        self._files = file_scanner
        self._links = link_analyzer or LinkAnalyzer()
        self._bursts = burst_detector or BurstDetector()
        self._admins = admin_cache or AdminCache()
        self._digest = digest
        self._autonomy = autonomy
        self._skip_admins = skip_group_admins
        self._trust_after = trust_after_messages
        # One cooldown per subsystem: a dead vision endpoint and a dead LLM
        # are different outages and each deserves to be heard once.
        self._degraded_warned_at: dict[str, float] = {}

    # --- one entry point for every user message -------------------------
    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Text, captions and attachments — new messages and edits alike.

        These are deliberately NOT separate handlers. python-telegram-bot runs
        only the first matching handler in a group, so a photo carrying both a
        scam caption and a fake .apk would have been judged on one and never the
        other. Here both signals are gathered and the harsher outcome wins.

        Two bypasses this closes:
          - captions were invisible (filters.TEXT does not match them)
          - edits were never even subscribed to, so "hi" -> edit to the pitch
            walked straight through
        """
        msg = update.effective_message
        if not msg or not update.effective_user:
            return
        user = update.effective_user
        if user.is_bot:
            return

        # Anonymous admins and channel posts arrive with sender_chat set and a
        # placeholder from_user; there is no user to judge or act on.
        if getattr(msg, "sender_chat", None) is not None:
            return

        # Group admins cannot be deleted or banned by a bot, so moderating them
        # only produces alerts nobody can action. Checked before any analysis so
        # it costs no LLM call. (Cached per chat — see AdminCache.)
        if self._skip_admins and await self._admins.is_admin(
            context.bot, msg.chat_id, user.id
        ):
            return

        # Where the words came from matters to a reviewer: a caption on a photo
        # and a plain message read identically in an alert otherwise, so there
        # is no way to tell which path caught it.
        text = msg.text or msg.caption or ""
        via = "caption" if (not msg.text and msg.caption) else "text"
        file_verdict = (
            self._files.scan_attachment(msg) if self._files
            else Verdict(Risk.CLEAN, "no file scanner", "file")
        )
        if not text and file_verdict.clean:
            return

        # An edit re-judges a message we may already have passed, so it must not
        # inflate the sender's message count.
        edited = bool(update.edited_message or update.edited_channel_post)
        bot = context.bot
        record = (
            await self._store.get(msg.chat_id, user.id) if edited
            else await self._store.touch(msg.chat_id, user.id, user.username or "")
        )

        # An admin has vouched for this person — don't spend an LLM call, and
        # don't let a keyword coincidence drag them back into the queue.
        if record.whitelisted:
            return

        trusted = record.trusted(self._trust_after)
        candidates: list[tuple[object, Verdict, Verdict | None]] = []

        # --- pace. Content-blind and free: how fast someone posts is evidence
        # no rewording can evade. Edits do not count as new messages.
        if not edited:
            burst = self._bursts.record(msg.chat_id, user.id)
            if not burst.clean and not trusted:
                # Established members get the benefit of the doubt on pace —
                # an excited regular in an argument is not a spammer.
                profile = await self._profiles.analyze(bot, user.id)
                candidates.append((
                    # Pace is capped at DELETE and earns no strike: remove the
                    # flood, but never ban someone for typing fast, and never
                    # let a burst leave a mark that escalates a later message.
                    # Someone splitting one thought across ten lines is not a
                    # scammer, and content evidence can still ban them.
                    self._policy.decide(
                        burst, profile, strikes=record.strikes, trusted=trusted,
                        ceiling=Action.DELETE, allow_strike=False,
                    ),
                    burst,
                    profile,
                ))
            # A wave of brand-new accounts is a raid, not a coincidence.
            if record.messages_seen == 0 and self._bursts.note_new_account(
                msg.chat_id, user.id
            ):
                await self._view.report_to_admins(
                    bot,
                    f"🌊 Possible raid in {msg.chat_id}: "
                    f"{self._bursts.raid_size(msg.chat_id)} new accounts posting "
                    "in the last minute. Alerts will be batched while this "
                    "lasts. Nothing is being auto-banned on pace alone.",
                )

        # --- the file, if any. Judged on its own: a fake 'wallet.apk' IS the
        # attack, so it needs no profile confirmation.
        if not file_verdict.clean:
            candidates.append(
                (file_decision(file_verdict, strikes=record.strikes), file_verdict, None)
            )

        # --- the words, if any.
        if text:
            # A non-matching keyword pass is recorded as an explicit CLEAN
            # rather than None, so the alert can show that it ran and found
            # nothing — "one detector fired" and "three agreed" should be
            # distinguishable in the review queue.
            keyword = self._keywords.check(text) or Verdict(
                Risk.CLEAN, "no pattern matched", "keyword"
            )
            # Links are checked with the keywords: both are free, and a
            # structurally deceptive URL is strong evidence on its own.
            link = self._links.analyze(text)
            if not link.clean or self._worth_llm(text, keyword):
                llm = await self._llm.analyze(
                    text, context=self._describe(record, trusted, text)
                )
                content = Verdict.worst(llm, keyword, link)
                # The model could not be reached. Keyword matching still works,
                # so keep moderating on that — but say so once. Alerting per
                # message would flood the queue during a multi-hour outage.
                if content.degraded:
                    await self._warn_degraded(bot, "language model", llm.reason)
                if not content.clean:
                    profile = await self._profiles.analyze(bot, user.id)
                    if profile.degraded:
                        await self._warn_degraded(
                            bot, "photo screening", profile.reason
                        )
                    candidates.append((
                        self._policy.decide(
                            content, profile, strikes=record.strikes, trusted=trusted
                        ),
                        content,
                        profile,
                    ))

        if not candidates:
            return

        # Both signals may have fired; the harsher response wins.
        decision, content, profile = max(
            candidates, key=lambda c: c[0].action.rank
        )
        chat_title = getattr(update.effective_chat, "title", "") or ""
        await self._apply(
            bot, msg.chat_id, msg.message_id, user, decision, content, profile,
            # The file's verdict is already in the breakdown above; repeating
            # it here just doubled a 130-character line.
            text or "(no message text — attachment only)", edited=edited,
            via=via if text else "file", chat_title=chat_title,
        )

    # --- new members -----------------------------------------------------
    async def handle_new_members(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Screen joiners before they post. Nobody is banned on joining — a bad
        profile only earns a heads-up, because a profile is not an offence."""
        msg = update.effective_message
        if not msg or not msg.new_chat_members:
            return
        for member in msg.new_chat_members:
            if member.is_bot:
                continue
            record = await self._store.get(msg.chat_id, member.id)
            if record.whitelisted:
                continue
            profile = await self._profiles.analyze(context.bot, member.id)
            if profile.risk is Risk.RED_FLAG:
                await self._view.report_to_admins(
                    context.bot,
                    f"👤 Joined — user={member.id} (@{member.username}) "
                    f"profile={profile.risk.value}: {profile.reason}",
                    chat_id=msg.chat_id,
                    user_id=member.id,
                )

    # --- shared tail -----------------------------------------------------
    async def _apply(
        self, bot, chat_id: int, message_id: int, user, decision,
        content: Verdict, profile: Verdict | None, text: str,
        edited: bool = False, via: str = "text", chat_title: str = "",
    ) -> None:
        # Autonomy governs what the bot CARRIES OUT and who it interrupts — the
        # policy remains the single place where severity is decided.
        action = self._autonomy.permit(decision.action)
        if action is Action.NONE:
            return

        user_strikes = 0
        if decision.add_strike:
            user_strikes = await self._store.add_strike(chat_id, user.id)

        # Every signal is listed, not just the one that won the tie. Whether a
        # single detector fired or three agreed independently is the difference
        # between a guess and a confirmation, and only the reviewer can weigh it.
        summary = (
            f"user={user.id} (@{user.username}) in {chat_id}"
            + (" [EDITED MESSAGE]" if edited else "")
            + "\n"
            + f"content={content.risk.value}\n{content.breakdown()}\n"
            + (
                f"profile={profile.risk.value}\n{profile.breakdown()}\n"
                if profile else ""
            )
            + (
                "⚠️ a signal is DEGRADED (marked ?) — it could not run, so this "
                "verdict is missing evidence\n"
                if content.degraded or (profile and profile.degraded) else ""
            )
            + f"decision={action.value} — {decision.reason}"
            + (f"\nstrikes={user_strikes}" if decision.add_strike else "")
            + f"\n{via}: {text[:200]}"
        )
        log.info("%s | %s", action.value, summary.replace("\n", " | "))

        if action.deletes:
            await self._view.delete_message(bot, chat_id, message_id)
        if action.bans:
            await self._view.kick_user(bot, chat_id, user.id)
            await self._store.set_status(chat_id, user.id, STATUS_BANNED)

        await self._store.log_event(
            chat_id, user.id, action.value, content.risk.value, decision.reason, text
        )
        if self._autonomy.alerts_live(action) or self._digest is None:
            await self._view.report_to_admins(
                bot,
                f"{_ICON[action]}\n{summary}",
                chat_id=chat_id,
                user_id=user.id,
                banned=action.bans,
            )
        else:
            # Already handled and low-stakes: fold it into the next digest
            # rather than pinging a human per removed spam line. With no digest
            # configured we alert anyway — never drop a finding silently.
            await self._digest.add(
                chat_id, chat_title, action.value, user.username or "",
                user.id, decision.reason,
            )

    async def _warn_degraded(self, bot, subsystem: str, reason: str) -> None:
        """Tell the admins a detector is unreachable — once per cooldown per
        subsystem, not once per message. An outage must be visible without
        being a flood.

        A screening step that is quietly dead is worse than one switched off,
        because it still looks like it is working.
        """
        now = time.monotonic()
        last = self._degraded_warned_at.get(subsystem, -DEGRADED_WARN_COOLDOWN)
        if now - last < DEGRADED_WARN_COOLDOWN:
            return
        self._degraded_warned_at[subsystem] = now
        log.error("%s degraded: %s", subsystem, reason)
        still_working = {
            "language model": "Keyword, link and file checks still run",
            "photo screening": "Text, link and file checks still run",
        }.get(subsystem, "Other checks still run")
        await self._view.report_to_admins(
            bot,
            f"⚠️ ScamGuard {subsystem} is DEGRADED\n"
            f"Unreachable: {reason[:200]}\n"
            f"{still_working}, but this signal is missing until it recovers. "
            "Nothing is being auto-banned on its behalf.",
        )

    def _worth_llm(self, text: str, keyword: Verdict) -> bool:
        """The one safe way to save calls: a very short message with no link,
        no mention and no keyword hit ("ok", "thanks", "👍") cannot carry a
        scam pitch. Anything longer goes to the model."""
        if not keyword.clean:
            return True
        stripped = text.strip()
        if len(stripped) >= MIN_LLM_CHARS:
            return True
        return any(m in stripped.lower() for m in ("http", "t.me", "@", "www."))

    def _describe(self, record, trusted: bool, text: str = "") -> str:
        """A one-line sender prior for the model. Deliberately coarse — we give
        it tenure and strikes, never a name it could be biased by."""
        if record.messages_seen == 0:
            sender = "SENDER CONTEXT: first message ever seen from this account."
        else:
            sender = (
                f"SENDER CONTEXT: {record.messages_seen} prior messages, "
                f"{record.strikes} prior strikes, "
                f"{'established member' if trusted else 'not yet established'}."
            )
        # Hand the model the hosts explicitly so it does not have to parse URLs
        # out of prose to reason about them.
        links = self._links.describe(text) if text else ""
        return f"{sender}\n{links}" if links else sender
