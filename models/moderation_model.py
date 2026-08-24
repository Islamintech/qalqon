"""The Model: all moderation logic and all moderation state.

Everything about *what should happen to a message* lives here. The Controller
below it only translates Telegram updates into these calls; the Views above it
only react to what this publishes. Neither of them decides anything.

Two consequences worth stating, because they are the point of the arrangement:

  - This module never imports telegram. It is handed plain dataclasses
    (IncomingMessage, JoiningMember) and hands back events. You could drive it
    from a CLI, a test, or a different chat platform without changing a line.
  - It never calls a View. It publishes what happened and moves on. Whether
    that becomes a Telegram alert, a digest line, or nothing at all is not its
    concern — which is why adding an output channel needs no edit here.

The decision itself is delegated further down to Policy, which is pure. This
class gathers evidence and applies the outcome; it does not contain the
escalation rules.
"""
import logging
import time
from dataclasses import dataclass

from .autonomy import Autonomy
from .events import (
    CaseResolved, DetectorDegraded, MemberJoined, MessageJudged, Observable,
    RaidDetected,
)
from .policy import Policy, file_decision
from .store import STATUS_BANNED, STATUS_NORMAL, STATUS_WHITELISTED, Store
from .verdict import Action, Risk, Verdict

log = logging.getLogger("scamguard.model")

# Below this length, a message with no link/mention/keyword hit is not worth an
# LLM call. Short group chatter ("ok", "thanks") is most of the traffic.
MIN_LLM_CHARS = 12

# How long to stay quiet after announcing that a detector is unreachable.
DEGRADED_COOLDOWN = 1800.0  # 30 minutes


@dataclass
class Attachment:
    """A file as DECLARED by the sender. Telegram guarantees nothing about the
    contents, and this is never opened."""

    file_name: str = ""
    mime_type: str | None = None
    file_size: int | None = None


@dataclass
class IncomingMessage:
    """A message, stripped of anything Telegram-shaped.

    The Controller builds this; the Model never sees an Update object. `via`
    records whether the words came from the body or a caption, because a
    reviewer needs to know which path caught it.
    """

    chat_id: int
    message_id: int
    user_id: int
    username: str = ""
    chat_title: str = ""
    text: str = ""
    via: str = "text"
    edited: bool = False
    attachment: Attachment | None = None


@dataclass
class JoiningMember:
    chat_id: int
    user_id: int
    username: str = ""


class ModerationModel(Observable):
    def __init__(
        self,
        *,
        store: Store,
        policy: Policy,
        keyword_filter,
        llm_client,
        profile_analyzer,
        link_analyzer,
        burst_detector,
        file_scanner,
        autonomy: Autonomy = Autonomy.ASSISTED,
        trust_after_messages: int = 25,
    ) -> None:
        super().__init__()
        self._store = store
        self._policy = policy
        self._keywords = keyword_filter
        self._llm = llm_client
        self._profiles = profile_analyzer
        self._links = link_analyzer
        self._bursts = burst_detector
        self._files = file_scanner
        self._autonomy = autonomy
        self._trust_after = trust_after_messages
        # One cooldown per subsystem: a dead vision endpoint and a dead LLM are
        # different outages and each deserves to be heard once.
        self._degraded_at: dict[str, float] = {}

    # --- the main path -----------------------------------------------------
    async def judge(self, msg: IncomingMessage) -> None:
        """Assess a message, apply the outcome, and announce it."""
        file_verdict = self._scan_file(msg.attachment)
        if not msg.text and file_verdict.clean:
            return

        # An edit re-judges a message we may already have passed, so it must not
        # inflate the sender's message count — otherwise editing one message
        # repeatedly would farm tenure toward the trust threshold.
        record = (
            await self._store.get(msg.chat_id, msg.user_id) if msg.edited
            else await self._store.touch(msg.chat_id, msg.user_id, msg.username)
        )
        if record.whitelisted:
            return

        trusted = record.trusted(self._trust_after)
        candidates: list[tuple] = []

        # --- pace: content-blind, so no rewording evades it -----------------
        if not msg.edited:
            burst = self._bursts.record(msg.chat_id, msg.user_id)
            if not burst.clean and not trusted:
                profile = await self._profile(msg.user_id)
                candidates.append((
                    # Capped at DELETE and earns no strike: remove the flood,
                    # but never ban someone for typing fast, and never let a
                    # burst leave a mark that escalates a later message.
                    self._policy.decide(
                        burst, profile, strikes=record.strikes, trusted=trusted,
                        ceiling=Action.DELETE, allow_strike=False,
                    ),
                    burst, profile,
                ))
            if record.messages_seen == 0 and self._bursts.note_new_account(
                msg.chat_id, msg.user_id
            ):
                await self.publish(RaidDetected(
                    chat_id=msg.chat_id,
                    accounts=self._bursts.raid_size(msg.chat_id),
                ))

        # --- the file: judged alone, because it IS the attack ---------------
        if not file_verdict.clean:
            candidates.append((
                file_decision(file_verdict, strikes=record.strikes),
                file_verdict, None,
            ))

        # --- the words ------------------------------------------------------
        if msg.text:
            keyword = self._keywords.check(msg.text) or Verdict(
                Risk.CLEAN, "no pattern matched", "keyword"
            )
            link = self._links.analyze(msg.text)
            if not link.clean or self._worth_llm(msg.text, keyword):
                llm = await self._llm.analyze(
                    msg.text, context=self._describe(record, trusted, msg.text)
                )
                content = Verdict.worst(llm, keyword, link)
                if content.degraded:
                    await self._announce_degraded("language model", llm.reason)
                if not content.clean:
                    profile = await self._profile(msg.user_id)
                    if profile.degraded:
                        await self._announce_degraded(
                            "photo screening", profile.reason
                        )
                    candidates.append((
                        self._policy.decide(
                            content, profile, strikes=record.strikes,
                            trusted=trusted,
                        ),
                        content, profile,
                    ))

        if not candidates:
            return
        decision, content, profile = max(candidates, key=lambda c: c[0].action.rank)
        await self._apply(msg, decision, content, profile)

    async def screen_joiner(self, member: JoiningMember) -> None:
        """Nobody is banned for joining — a profile is not an offence — so this
        only ever announces."""
        record = await self._store.get(member.chat_id, member.user_id)
        if record.whitelisted:
            return
        profile = await self._profile(member.user_id)
        if profile.risk is Risk.RED_FLAG:
            await self.publish(MemberJoined(
                chat_id=member.chat_id, user_id=member.user_id,
                username=member.username, profile=profile,
            ))

    # --- admin overrides ---------------------------------------------------
    async def resolve(
        self, chat_id: int, user_id: int, verb: str,
        by_user_id: int, by_username: str = "",
    ) -> str | None:
        """Apply an admin's decision and record whether they overturned us.

        That flag is ground truth: tapping Ignore means a human judged the bot
        wrong, tapping Ban means they judged it right. Nothing else in the
        system is an unbiased signal of the false-positive rate.
        """
        outcomes = {
            "ban": (STATUS_BANNED, "banned 🚫", False),
            "unban": (STATUS_NORMAL, "unbanned ♻️", True),
            "ok": (None, "ignored — strikes cleared 👌", True),
            "wl": (STATUS_WHITELISTED, "whitelisted ✅", True),
        }
        if verb not in outcomes:
            return None
        status, note, overturned = outcomes[verb]

        if verb in ("unban", "ok"):
            # A false positive must not leave a strike behind to escalate on.
            await self._store.clear_strikes(chat_id, user_id)
        if status is not None:
            await self._store.set_status(chat_id, user_id, status)

        await self._store.log_event(
            chat_id, user_id, f"ADMIN_{verb.upper()}",
            "OVERTURNED" if overturned else "CONFIRMED",
            f"by admin {by_user_id} (@{by_username or '?'})",
        )
        await self.publish(CaseResolved(
            chat_id=chat_id, user_id=user_id, verb=verb,
            by_user_id=by_user_id, by_username=by_username,
            note=note, overturned=overturned,
        ))
        return note

    # --- internals ---------------------------------------------------------
    async def _apply(self, msg, decision, content, profile) -> None:
        # Autonomy governs what is CARRIED OUT and who is interrupted; Policy
        # remains the single place severity is decided.
        action = self._autonomy.permit(decision.action)
        if action is Action.NONE:
            return

        strikes = 0
        if decision.add_strike:
            strikes = await self._store.add_strike(msg.chat_id, msg.user_id)
        if action.bans:
            await self._store.set_status(msg.chat_id, msg.user_id, STATUS_BANNED)
        await self._store.log_event(
            msg.chat_id, msg.user_id, action.value, content.risk.value,
            decision.reason, msg.text,
        )

        event = MessageJudged(
            chat_id=msg.chat_id, chat_title=msg.chat_title,
            message_id=msg.message_id, user_id=msg.user_id,
            username=msg.username, action=action, reason=decision.reason,
            content=content, profile=profile, text=msg.text, via=msg.via,
            edited=msg.edited, strikes=strikes, struck=decision.add_strike,
        )
        log.info("%s | %s", action.value, event.summary.replace("\n", " | "))
        await self.publish(event)

    def _scan_file(self, attachment: Attachment | None) -> Verdict:
        if attachment is None or not self._files:
            return Verdict(Risk.CLEAN, "no attachment", "file")
        return self._files.scan(
            attachment.file_name, attachment.mime_type, attachment.file_size
        )

    async def _profile(self, user_id: int) -> Verdict:
        return await self._profiles.analyze(user_id)

    async def _announce_degraded(self, subsystem: str, reason: str) -> None:
        """Once per cooldown per subsystem. The rate limit is domain policy —
        an outage must be visible without being a flood — so it lives here
        rather than in whichever View happens to render it."""
        now = time.monotonic()
        if now - self._degraded_at.get(subsystem, -DEGRADED_COOLDOWN) < DEGRADED_COOLDOWN:
            return
        self._degraded_at[subsystem] = now
        log.error("%s degraded: %s", subsystem, reason)
        await self.publish(DetectorDegraded(subsystem=subsystem, reason=reason))

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
        """A coarse sender prior for the model — tenure and strikes, never a
        name it could be biased by."""
        if record.messages_seen == 0:
            sender = "SENDER CONTEXT: first message ever seen from this account."
        else:
            sender = (
                f"SENDER CONTEXT: {record.messages_seen} prior messages, "
                f"{record.strikes} prior strikes, "
                f"{'established member' if trusted else 'not yet established'}."
            )
        links = self._links.describe(text) if text else ""
        return f"{sender}\n{links}" if links else sender
