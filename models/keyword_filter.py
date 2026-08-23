"""Fast, cheap first pass. Catches the obvious scam openers with regex so we
don't burn an LLM call on every 'hello'. A hit here raises suspicion to
FIFTY_FIFTY and lets the controller decide whether to escalate — it does NOT
ban on its own, because keyword matching false-positives easily."""
import re

from .verdict import Verdict, Risk

# Add/tune these over time. Keep them lowercase; matching is case-insensitive.
SCAM_PATTERNS: list[str] = [
    r"\bcheck (out )?my profile\b",
    r"\blook at my (profile|channel|page)\b",
    r"\bis (anyone|someone) (free|available|online|there)\b",
    r"\bdm me\b",
    r"\btext me (on|at)\b",
    r"\b(add|contact) me on (whatsapp|telegram|instagram)\b",
    r"\bearn \$?\d+.{0,15}(day|week|hour)\b",
    r"\b(crypto|forex|investment).{0,20}(profit|guaranteed|returns)\b",
    r"\bfree (money|gift|giveaway)\b",
]


class KeywordFilter:
    def __init__(self, patterns: list[str] | None = None) -> None:
        self._regexes = [
            re.compile(p, re.IGNORECASE) for p in (patterns or SCAM_PATTERNS)
        ]

    def check(self, text: str) -> Verdict | None:
        """Return a FIFTY_FIFTY verdict on first match, else None."""
        for rx in self._regexes:
            if rx.search(text):
                return Verdict(
                    risk=Risk.FIFTY_FIFTY,
                    reason=f"keyword pattern matched: /{rx.pattern}/",
                    source="keyword",
                )
        return None
