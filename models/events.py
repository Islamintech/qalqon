"""Domain events, and the observer registry the Model notifies through.

This is the piece that makes the architecture actually Model–View–Controller
rather than MVC in name only. In classical MVC the View observes the Model and
renders its state; the Controller never tells the View what to do. A chat bot
has no rendering surface, so the event-driven reading of MVC applies:

    Controller  →  Model  →  (notifies)  →  View

The Controller translates an incoming Telegram update into a domain call and
stops there. The Model decides, records, and announces what happened. Views
subscribe and react — one sends Telegram alerts, another accumulates a digest.

What this buys, beyond the label: adding an output channel stops being an edit
to the Controller. A webhook, an email digest, a metrics exporter — each is a
new subscriber, and the decision logic never learns they exist.

Events are plain frozen dataclasses carrying everything a subscriber needs, so
a View never has to reach back into the Model to render one. They describe what
HAPPENED, in past tense — never what someone should do about it. The moment an
event says "send an alert", the Model is issuing orders to a View again and the
separation is gone.
"""
import asyncio
import logging
from dataclasses import dataclass, field

from .verdict import Action, Verdict

log = logging.getLogger("scamguard.events")


# --- events ----------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    """Base class, so a subscriber can accept anything and filter."""


@dataclass(frozen=True)
class MessageJudged(Event):
    """A message was assessed and the Model has already carried out its
    decision on the record (strikes, status, event log). What remains is
    telling people about it."""

    chat_id: int
    chat_title: str
    message_id: int
    user_id: int
    username: str
    action: Action
    reason: str
    content: Verdict
    profile: Verdict | None
    text: str
    via: str = "text"
    edited: bool = False
    strikes: int = 0
    struck: bool = False

    @property
    def summary(self) -> str:
        """Rendered here rather than in a View because every View wants the
        same words, and two renderings would drift apart."""
        parts = [
            f"user={self.user_id} (@{self.username or '?'}) in {self.chat_id}"
            + (" [EDITED MESSAGE]" if self.edited else ""),
            f"content={self.content.risk.value}\n{self.content.breakdown()}",
        ]
        if self.profile is not None:
            parts.append(
                f"profile={self.profile.risk.value}\n{self.profile.breakdown()}"
            )
        if self.content.degraded or (self.profile and self.profile.degraded):
            parts.append(
                "⚠️ a signal is DEGRADED (marked ?) — it could not run, so this "
                "verdict is missing evidence"
            )
        parts.append(f"decision={self.action.value} — {self.reason}")
        if self.struck:
            parts.append(f"strikes={self.strikes}")
        parts.append(f"{self.via}: {self.text[:200]}")
        return "\n".join(parts)


@dataclass(frozen=True)
class MemberJoined(Event):
    """Someone joined and their profile looked bad. Nobody is banned for a
    profile, so this is informational by construction."""

    chat_id: int
    user_id: int
    username: str
    profile: Verdict


@dataclass(frozen=True)
class RaidDetected(Event):
    chat_id: int
    accounts: int


@dataclass(frozen=True)
class DetectorDegraded(Event):
    """A detector could not run. Announced once per cooldown by the Model, not
    once per message — the cooldown is domain policy, not presentation."""

    subsystem: str
    reason: str


@dataclass(frozen=True)
class CaseResolved(Event):
    """An admin overrode or confirmed a decision. `overturned` is the ground
    truth the accuracy figures are built from."""

    chat_id: int
    user_id: int
    verb: str
    by_user_id: int
    by_username: str
    note: str
    overturned: bool


# --- the registry ----------------------------------------------------------
@dataclass
class Observable:
    """Minimal synchronous-registration, asynchronous-dispatch observer list.

    A subscriber that raises is logged and skipped: a View failing to render
    must never abort the Model's work or stop the other Views. The moderation
    decision has already been carried out by the time anything is published —
    an alert that fails to send does not un-ban anyone.
    """

    _subscribers: list = field(default_factory=list)

    def subscribe(self, handler) -> None:
        self._subscribers.append(handler)

    async def publish(self, event: Event) -> None:
        for handler in list(self._subscribers):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                log.warning(
                    "subscriber %s failed on %s: %s",
                    getattr(handler, "__qualname__", handler),
                    type(event).__name__, exc,
                )
