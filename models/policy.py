r"""The escalation brain, as a PURE function of (content, profile, history).

Kept free of Telegram and of I/O on purpose: this is the safety-critical part,
so it must be exhaustively testable. The controller gathers evidence, the
policy decides, the view acts.

Base matrix (no history):

    content \ profile | CLEAN      FIFTY_FIFTY   RED_FLAG
    ------------------+------------------------------------
    CLEAN             | NONE       NONE          NONE
    FIFTY_FIFTY       | REVIEW     REVIEW        DELETE
    RED_FLAG          | DELETE     BAN           BAN

Then two adjustments:
  - trusted user  -> never worse than REVIEW (a long-standing member is not
    getting auto-banned over one bad-looking sentence)
  - repeat strikes-> escalate one step per threshold reached
"""
from dataclasses import dataclass

from .verdict import Action, Risk, Verdict

_BASE: dict[tuple[Risk, Risk], Action] = {
    (Risk.CLEAN, Risk.CLEAN): Action.NONE,
    (Risk.CLEAN, Risk.FIFTY_FIFTY): Action.NONE,
    (Risk.CLEAN, Risk.RED_FLAG): Action.NONE,
    (Risk.FIFTY_FIFTY, Risk.CLEAN): Action.REVIEW,
    (Risk.FIFTY_FIFTY, Risk.FIFTY_FIFTY): Action.REVIEW,
    (Risk.FIFTY_FIFTY, Risk.RED_FLAG): Action.DELETE,
    (Risk.RED_FLAG, Risk.CLEAN): Action.DELETE,
    (Risk.RED_FLAG, Risk.FIFTY_FIFTY): Action.BAN,
    (Risk.RED_FLAG, Risk.RED_FLAG): Action.BAN,
}

_LADDER = [Action.NONE, Action.REVIEW, Action.DELETE, Action.BAN]


def _escalate(action: Action, steps: int) -> Action:
    idx = min(_LADDER.index(action) + max(steps, 0), len(_LADDER) - 1)
    return _LADDER[idx]


def _cap(action: Action, ceiling: Action) -> Action:
    return action if action.rank <= ceiling.rank else ceiling


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str
    add_strike: bool

    @property
    def acted(self) -> bool:
        return self.action is not Action.NONE


class Policy:
    def __init__(
        self,
        require_profile_confirmation: bool = True,
        strikes_to_escalate: int = 2,
        trusted_ceiling: Action = Action.REVIEW,
    ) -> None:
        self._require_profile = require_profile_confirmation
        self._strikes_to_escalate = max(strikes_to_escalate, 1)
        self._trusted_ceiling = trusted_ceiling

    def decide(
        self,
        content: Verdict,
        profile: Verdict | None = None,
        strikes: int = 0,
        trusted: bool = False,
        ceiling: Action | None = None,
        allow_strike: bool = True,
    ) -> Decision:
        """`ceiling` caps how far this evidence can escalate, and `allow_strike`
        stops it leaving a permanent mark. Both exist for evidence that is real
        but weak on its own — posting pace, for instance: a flood should be
        removed, but nobody should be banned for typing fast, and an innocent
        fast poster must not accumulate strikes that escalate a later message.
        """
        if content.clean:
            return Decision(Action.NONE, "content clean", add_strike=False)

        notes = [f"content={content.risk.value}({content.source})"]

        if not self._require_profile:
            # Profile confirmation disabled: judge on content alone.
            action = Action.BAN if content.risk is Risk.RED_FLAG else Action.REVIEW
            notes.append("profile-confirmation off")
        else:
            prof = profile or Verdict(Risk.CLEAN, "profile not checked", "profile")
            action = _BASE[(content.risk, prof.risk)]
            notes.append(f"profile={prof.risk.value}")

        # Repeat offender: every full threshold of strikes moves one step up.
        steps = strikes // self._strikes_to_escalate
        if steps and action is not Action.NONE:
            action = _escalate(action, steps)
            notes.append(f"strikes={strikes} (+{steps})")

        # Trust cap comes LAST so it overrides strike escalation. A member with
        # a long clean record gets a human look, never a silent auto-ban.
        if trusted:
            capped = _cap(action, self._trusted_ceiling)
            if capped is not action:
                notes.append(f"trusted: {action.value}->{capped.value}")
            action = capped

        if ceiling is not None:
            capped = _cap(action, ceiling)
            if capped is not action:
                notes.append(f"capped at {ceiling.value}")
            action = capped

        # A strike is only earned when the evidence was strong enough to act on
        # the message itself. REVIEW alone must not snowball into a ban.
        add_strike = action.deletes and allow_strike
        return Decision(action, "; ".join(notes), add_strike=add_strike)


def file_decision(verdict: Verdict, strikes: int = 0) -> Decision:
    """Files are judged on their own — a fake 'wallet.apk' IS the attack, so it
    needs no profile confirmation. Repeat file offenders go straight to a ban."""
    if verdict.clean:
        return Decision(Action.NONE, "file clean", add_strike=False)
    if verdict.risk is Risk.RED_FLAG:
        action = Action.BAN if strikes >= 1 else Action.DELETE
    else:
        action = Action.REVIEW
    return Decision(action, f"file: {verdict.reason}", add_strike=action.deletes)
