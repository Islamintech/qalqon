"""Shared vocabulary that every layer speaks: Risk, Verdict, Action."""
from dataclasses import dataclass, field, replace
from enum import Enum


class Risk(str, Enum):
    CLEAN = "CLEAN"
    FIFTY_FIFTY = "FIFTY_FIFTY"
    RED_FLAG = "RED_FLAG"

    @property
    def rank(self) -> int:
        return {"CLEAN": 0, "FIFTY_FIFTY": 1, "RED_FLAG": 2}[self.value]


class Action(str, Enum):
    """What the controller decided to do. Ordered by severity."""

    NONE = "NONE"        # nothing happened, message stays
    REVIEW = "REVIEW"    # message stays, admins get an alert
    DELETE = "DELETE"    # message removed, user stays, admins alerted
    BAN = "BAN"          # message removed and user banned

    @property
    def rank(self) -> int:
        return {"NONE": 0, "REVIEW": 1, "DELETE": 2, "BAN": 3}[self.value]

    @property
    def deletes(self) -> bool:
        return self.rank >= Action.DELETE.rank

    @property
    def bans(self) -> bool:
        return self is Action.BAN


@dataclass
class Verdict:
    risk: Risk
    reason: str
    source: str  # keyword/llm/link/burst/file/bio/photo/vision/channel
    # True when this verdict is a fallback because the analyzer could not run —
    # NOT the same as "the analyzer looked and found nothing". CLEAN because we
    # never got an answer must never be mistaken for CLEAN on the evidence.
    degraded: bool = False
    # What this verdict was combined FROM, when it is a composite. Only the
    # winning signal survives into risk/reason, so without this an alert cannot
    # say whether one detector fired or three independently agreed — and
    # "three agree" is far stronger evidence than one model's opinion.
    # Excluded from equality so verdicts still compare on their substance.
    components: tuple["Verdict", ...] = field(default=(), compare=False, repr=False)

    @staticmethod
    def worst(*verdicts: "Verdict") -> "Verdict":
        """Highest-risk verdict of those given. Safe on an empty call.

        The result keeps every input in `components`, so the reasoning stays
        inspectable after the collapse.
        """
        if not verdicts:
            return Verdict(Risk.CLEAN, "nothing to judge", "none")
        worst = max(verdicts, key=lambda v: v.risk.rank)
        # Degradation is sticky: if any input was a fallback, the combined
        # verdict is only as trustworthy as that gap.
        degraded = worst.degraded or any(v.degraded for v in verdicts)
        # Flatten one level: a component's own components would nest without
        # limit through profile -> vision -> ... and nobody reads that.
        return replace(
            worst,
            degraded=degraded,
            components=tuple(replace(v, components=()) for v in verdicts),
        )

    @property
    def clean(self) -> bool:
        return self.risk is Risk.CLEAN

    def breakdown(self, indent: str = "  ") -> str:
        """Human-readable list of the signals behind this verdict, for alerts.
        Falls back to the verdict itself when it is not a composite."""
        parts = self.components or (self,)
        lines = []
        for v in parts:
            mark = f"{v.risk.value}?" if v.degraded else v.risk.value
            reason = v.reason if len(v.reason) <= 150 else v.reason[:147] + "..."
            lines.append(f"{indent}{v.source:<8} {mark:<12} {reason}")
        return "\n".join(lines)
