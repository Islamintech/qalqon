"""How much the bot does on its own, and what it interrupts a human for.

Phase 1 assumed every borderline case would be read by a person. That premise
holds for one group and quietly fails for twenty: nobody reviews a queue that
never empties, so "route it to a human" becomes "ignore it" — while the scam
message stays up the whole time.

So the question stops being "should a human approve this?" and becomes "is this
worth interrupting a human for?" Those are different, and the answer depends on
whether the decision is (a) already made, (b) reversible, and (c) costly if
wrong:

  REVIEW  nothing happened yet and the evidence is ambiguous. A human genuinely
          has to decide, so this always interrupts.
  BAN     already done, and the most consequential thing the bot can do. It is
          reversible with one tap, but only if someone SEES it — so it
          interrupts too.
  DELETE  already done, low stakes (message gone, user stays). Batched into a
          digest; no reason to ping anyone at 3am for one removed spam line.

Modes:
  report      never act, only report. Safe, and useless at scale — the scam
              stays up until someone reads the alert.
  assisted    act as the policy decided; interrupt for REVIEW and BAN, digest
              the rest. The default.
  autonomous  act as the policy decided; interrupt for nothing, digest
              everything. Hands-off, and mistakes go unseen for longer.
"""
from enum import Enum

from .verdict import Action


class Autonomy(str, Enum):
    REPORT = "report"
    ASSISTED = "assisted"
    AUTONOMOUS = "autonomous"

    @classmethod
    def parse(cls, value: str, default: "Autonomy" = None) -> "Autonomy":
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return default or cls.ASSISTED

    def permit(self, action: Action) -> Action:
        """What the bot is actually allowed to carry out.

        In report mode anything that would have touched the chat is downgraded
        to REVIEW — the finding still reaches a human, but the bot's hands stay
        off. The other modes carry out whatever the policy decided; autonomy
        governs NOTIFICATION, not judgement, so that the escalation rules stay
        the single place where severity is decided.
        """
        if self is Autonomy.REPORT and action.rank > Action.REVIEW.rank:
            return Action.REVIEW
        return action

    def alerts_live(self, action: Action) -> bool:
        """Whether this warrants interrupting a human right now, as opposed to
        appearing in the next digest."""
        if action is Action.NONE:
            return False
        if self is Autonomy.AUTONOMOUS:
            return False
        if self is Autonomy.REPORT:
            return True
        # assisted: a decision to make, or a ban worth seeing quickly
        return action is Action.REVIEW or action is Action.BAN

    @property
    def acts(self) -> bool:
        return self is not Autonomy.REPORT
