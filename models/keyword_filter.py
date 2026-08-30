"""Fast, cheap first pass. Catches unambiguous scam openers with regex so we
don't burn an LLM call on every 'hello'. A hit raises suspicion to FIFTY_FIFTY
and lets the policy decide whether to escalate — it never bans on its own,
because regex false-positives easily.

WHAT BELONGS HERE, AND WHAT DOES NOT

These groups are Uzbek workers in South Korea. Their two most common messages
are daily work announcements and won <-> so'm currency exchange, and an
English-language scam ruleset flags both:

    "is anyone free tomorrow"      -> a shift request, not a lonely stranger
    "earn 130000 won a day"        -> a stated wage, not an earnings promise
    "dm me" / "contact me on telegram" -> how every exchange is arranged

Those patterns were removed. A regex cannot tell a job offer from a job scam,
because the difference is whether money is demanded UP FRONT — that is the
model's job, and the prompt in llm_client.py carries the context for it.

What is left is only what is unambiguous in any language: bait pointing at a
profile or channel, and explicit promises of guaranteed profit. Patterns are
multilingual, because these groups are — an English-only list both misses the
Uzbek version of a scam and reads oddly-translated Uzbek as suspicious.
"""
import re

from .verdict import Verdict, Risk

# Uzbek is written with several different apostrophes (o' o‘ oʻ oʼ) and often
# with none at all. Matching one shape only would miss most real messages.
APO = "['`‘’ʻʼ]?"

SCAM_PATTERNS: list[str] = [
    # --- bait pointing at a profile or channel (any language) --------------
    r"\bcheck (out )?my (profile|channel|page)\b",
    r"\blook at my (profile|channel|page)\b",
    # uz: "mening profilimni ko'ring", "profilimga kiring"
    rf"\bprofilim(ni|ga)?\b.{{0,15}}\b(ko{APO}r|kir|qara)",
    r"\bkanalim(ni|ga)?\b.{0,15}\b(kir|obuna)",
    # ru: "посмотри мой профиль", "заходи в мой канал"
    r"\b(посмотри|зайди|загляни)\w*\b.{0,15}\b(профил|канал)",

    # --- guaranteed returns / investment schemes ---------------------------
    r"\b(crypto|forex|investment)\b.{0,20}\b(profit|guaranteed|returns)\b",
    r"\bfree (money|gift|giveaway)\b",
    # uz: "kafolatlangan foyda", "foyda kafolatlanadi", "kuniga 10% foyda"
    r"\bkafolat\w*\b.{0,25}\b(foyda|daromad|pul)\b",
    r"\b(foyda|daromad)\b.{0,25}\bkafolat\w*",
    r"\bkuniga\s*\d{1,3}\s*%",
    # ru: "гарантированный доход", "20% в день"
    r"\bгарантирован\w*\b.{0,25}\b(доход|прибыл|заработ)",
    r"\b\d{1,3}\s*%\s*в\s*день\b",

    # --- money demanded UP FRONT, which is the real discriminator ---------
    # Kept narrow: it must say "in advance"/"first", not merely mention money.
    # uz: "oldindan to'lang", "oldindan 500$"
    rf"\boldindan\b.{{0,20}}\b(to{APO}la\w*|pul|\d)",
    # ru: "предоплата", "сначала переведите"
    r"\bпредоплат\w*",
    r"\bсначала\b.{0,20}\b(переве|оплат|отправ)",
    # uz: "avval siz o'tkazing/yuboring" — you go first
    rf"\bavval\s+siz\b.{{0,25}}\b(o{APO}tkaz|yubor|to{APO}la)",
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
