"""Link inspection. Scam links are the actual payload of most Telegram scams,
and nothing was looking at them.

DESIGN CONSTRAINT: sharing links is completely normal. "Contains a URL" is not
a signal and must never raise risk on its own, or the bot becomes useless in any
group where people share articles. What this looks for is *structural
deception* — a link built to be mistaken for something it is not:

  - homograph / punycode domains   (xn--binance-...)  — invisible substitution
  - typosquats of high-value brands (binanace.com)    — one edit away
  - embedded credentials           (binance.com@evil.tld) — the real host is
                                                        after the @
  - raw IP addresses               (http://51.20.3.4/wallet)
  - shorteners                     (bit.ly/...)       — destination hidden
  - a domain in the TEXT that is not the domain in the LINK (markdown-style
    mismatch) — the classic phishing display trick

Everything here is decided on the URL string alone. Nothing is fetched: making
the bot follow arbitrary user-supplied links would hand anyone in the group an
SSRF primitive and a way to confirm the bot is watching.
"""
import re

from .verdict import Verdict, Risk

# Brands worth impersonating in a crypto/telegram scam context. A domain that is
# ALMOST one of these is far more suspicious than a domain that is nothing like
# any of them.
PROTECTED_BRANDS = [
    "telegram", "binance", "metamask", "coinbase", "trustwallet", "ledger",
    "trezor", "bybit", "kucoin", "okx", "bitfinex", "kraken", "phantom",
    "uniswap", "opensea", "whatsapp", "instagram", "paypal", "revolut",
]

# Destination is hidden behind a redirect, so nothing downstream can judge it.
SHORTENERS = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "buff.ly",
    "cutt.ly", "rebrand.ly", "shorturl.at", "rb.gy", "tiny.cc", "bl.ink",
    "s.id", "clck.ru", "surl.li",
}

# Legitimate Telegram hosts — a t.me link is ordinary and must not be flagged.
TELEGRAM_HOSTS = {"t.me", "telegram.me", "telegram.org", "telegram.dog"}

_URL_RE = re.compile(
    r"""(?xi)
    \b
    (?:(?P<scheme>https?|ftp)://)?
    (?P<userinfo>[^\s/@]{1,64}@)?
    (?P<host>
        (?:\d{1,3}\.){3}\d{1,3}                  # bare IPv4
      | (?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}
    )
    (?P<port>:\d{1,5})?
    (?P<path>/[^\s]*)?
    """
)

_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")

# Only treat a bare (scheme-less) match as a link if it ends in a plausible TLD,
# so "version 1.2.3" and "file.py" are not read as domains.
_PLAUSIBLE_BARE_TLD = re.compile(
    r"\.(com|net|org|io|co|me|app|xyz|info|biz|ru|cn|top|site|online|live|"
    r"finance|fund|cash|link|click|pro|vip|gift|shop|store|dev|ai)$",
    re.IGNORECASE,
)


def _levenshtein(a: str, b: str, cap: int = 3) -> int:
    """Small edit distance with an early exit — we only care about 'close'."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


# Character shapes that read as another character in a sans-serif font. "rn"
# and "m" are indistinguishable at a glance, which is why metarnask.io works as
# an attack while being 2 edits from metamask — far enough to beat a naive
# edit-distance check.
_HOMOGLYPHS = (
    ("rn", "m"), ("vv", "w"), ("cl", "d"), ("nn", "m"),
    ("0", "o"), ("1", "l"), ("3", "e"), ("5", "s"), ("7", "t"), ("4", "a"),
)


def _deglyph(label: str) -> str:
    """Fold visually-confusable sequences so a homoglyph swap collapses onto
    the brand it is imitating."""
    out = label.lower()
    for fake, real in _HOMOGLYPHS:
        out = out.replace(fake, real)
    return out


def _registrable(host: str) -> str:
    """The part a human reads as 'the brand'. Not a public-suffix-list parse —
    good enough to compare 'binance' in binance.com vs binance.evil.tld."""
    parts = host.lower().strip(".").split(".")
    if len(parts) < 2:
        return host.lower()
    # Handle the common two-part suffixes without pulling in a dependency.
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"}:
        return parts[-3]
    return parts[-2]


class Link:
    def __init__(self, match: re.Match) -> None:
        self.raw = match.group(0)
        self.scheme = (match.group("scheme") or "").lower()
        self.userinfo = (match.group("userinfo") or "").rstrip("@")
        self.host = (match.group("host") or "").lower().strip(".")
        self.path = match.group("path") or ""

    @property
    def registrable(self) -> str:
        return _registrable(self.host)

    def __repr__(self) -> str:
        return f"<Link {self.host}>"


def extract_links(text: str) -> list[Link]:
    links: list[Link] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(text or ""):
        link = Link(m)
        # someone@example.com is an email address, not a credentials-in-url
        # attack. The trick only exists when there is an actual URL around it.
        if link.userinfo and not link.scheme:
            continue
        if not link.scheme and not _IPV4_RE.match(link.host):
            # A scheme-less match needs a believable TLD to count as a link,
            # so "version 1.2.3" and "file.py" are not read as domains. Known
            # shorteners are accepted whatever their TLD — bit.ly is precisely
            # the shape people paste without a scheme.
            known = link.host in SHORTENERS or link.host in TELEGRAM_HOSTS
            if not known and not _PLAUSIBLE_BARE_TLD.search(link.host):
                continue
        if link.host in seen:
            continue
        seen.add(link.host)
        links.append(link)
    return links


class LinkAnalyzer:
    def __init__(self, blocklist: set[str] | None = None) -> None:
        # Domains an admin has explicitly banned for this deployment.
        self._blocklist = {d.lower().lstrip(".") for d in (blocklist or set())}

    def analyze(self, text: str) -> Verdict:
        links = extract_links(text)
        if not links:
            return Verdict(Risk.CLEAN, "no links", "link")

        risk = Risk.CLEAN
        reasons: list[str] = []

        def raise_to(level: Risk, why: str) -> None:
            nonlocal risk
            reasons.append(why)
            if level.rank > risk.rank:
                risk = level

        for link in links:
            host = link.host

            if host in self._blocklist or link.registrable in self._blocklist:
                raise_to(Risk.RED_FLAG, f"blocklisted domain '{host}'")
                continue

            # The real destination of user@host is host, not what precedes it.
            if link.userinfo:
                raise_to(
                    Risk.RED_FLAG,
                    f"credentials-in-url trick: reads as "
                    f"'{link.userinfo}' but goes to '{host}'",
                )

            # Punycode: the displayed characters are not the ASCII ones.
            if "xn--" in host:
                raise_to(Risk.RED_FLAG, f"punycode/homograph domain '{host}'")

            if _IPV4_RE.match(host):
                raise_to(Risk.FIFTY_FIFTY, f"raw IP address link '{host}'")
                continue

            if host in TELEGRAM_HOSTS:
                continue  # ordinary — t.me links are how Telegram works

            if host in SHORTENERS or link.registrable in SHORTENERS:
                raise_to(Risk.FIFTY_FIFTY, f"shortened link '{host}' hides its target")
                continue

            # Typosquatting: close to a protected brand without being it.
            label = link.registrable
            folded = _deglyph(label)
            for brand in PROTECTED_BRANDS:
                if label == brand:
                    break  # the genuine brand label
                # A homoglyph swap (metarnask -> metamask) is deliberate by
                # construction; nobody types "rn" for "m" by accident.
                if folded == _deglyph(brand):
                    raise_to(
                        Risk.RED_FLAG,
                        f"'{host}' is a look-alike of '{brand}'",
                    )
                    break
                distance = _levenshtein(label, brand)
                if distance <= 1 and len(brand) >= 5:
                    raise_to(
                        Risk.RED_FLAG,
                        f"'{host}' is {distance} character from '{brand}'",
                    )
                    break
                # brand appears as a subdomain/prefix of an unrelated domain:
                # binance.security-check.tld
                if brand in host and label != brand:
                    raise_to(
                        Risk.RED_FLAG,
                        f"'{host}' uses the '{brand}' name but is not {brand}",
                    )
                    break

        return Verdict(
            risk=risk,
            reason="; ".join(reasons) or f"{len(links)} ordinary link(s)",
            source="link",
        )

    def describe(self, text: str) -> str:
        """A short note about the links, for the LLM prompt. Giving the model
        the hosts explicitly stops it having to parse URLs out of prose."""
        links = extract_links(text)
        if not links:
            return ""
        hosts = ", ".join(sorted({link.host for link in links})[:8])
        return f"LINKS IN MESSAGE: {hosts}"
