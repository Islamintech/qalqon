"""Telegram Login Widget verification and session cookies.

Telegram signs the login payload with HMAC-SHA256 using sha256(bot_token) as
the key. Anyone can POST whatever they like to the callback URL, so the
signature is the ONLY thing separating an admin from an attacker — every check
here is load-bearing:

  signature   proves Telegram produced this payload
  auth_date   proves it is recent; without it a captured login URL would work
              forever, since the payload never changes
  allow-list  proves this particular Telegram user is permitted. A valid
              signature only means "a real Telegram user", not "an admin" —
              anyone in the world can press the login button.

Sessions are signed cookies rather than server-side state: there is nothing
worth storing, and a stateless cookie cannot be desynchronised from a restart.
The cookie carries the user id and an expiry, signed with HMAC — it is signed,
not encrypted, so it must never contain anything secret.
"""
import hashlib
import hmac
import json
import logging
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

log = logging.getLogger("qalqon.web.auth")

# A login payload older than this is refused. Telegram recommends a short
# window; the widget redirects immediately, so a minute is generous.
MAX_AUTH_AGE = 300.0


def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_telegram_login(
    data: dict, bot_token: str, now: float | None = None
) -> int | None:
    """Return the Telegram user id if this payload genuinely came from Telegram
    and is fresh, else None. Never raises on malformed input — this is fed
    directly from a query string."""
    if not bot_token:
        return None
    received = data.get("hash")
    if not received:
        return None

    # Every field EXCEPT hash, sorted, joined with newlines. Fields we do not
    # recognise must still be included or the signature will not match.
    check = "\n".join(
        f"{k}={data[k]}" for k in sorted(data) if k != "hash" and data[k] is not None
    )
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()

    # Constant-time: a plain == leaks how much of the digest matched.
    if not hmac.compare_digest(expected, str(received)):
        log.warning("telegram login rejected: bad signature")
        return None

    try:
        auth_date = float(data.get("auth_date", 0))
        user_id = int(data["id"])
    except (TypeError, ValueError, KeyError):
        log.warning("telegram login rejected: malformed payload")
        return None

    age = (now if now is not None else time.time()) - auth_date
    if age > MAX_AUTH_AGE or age < -MAX_AUTH_AGE:
        # Without this, a login URL captured from a browser history or a proxy
        # log would stay valid forever.
        log.warning("telegram login rejected: stale (age %.0fs)", age)
        return None

    return user_id


def is_allowed(user_id: int, allowed: set[int]) -> bool:
    """A valid signature only proves the person is a real Telegram user —
    anyone in the world can press the login button. This is what proves they
    are one of YOUR admins.

    An empty allow-list denies everyone. Defaulting to open would mean a
    forgotten config value silently publishes every moderation record.
    """
    return bool(allowed) and user_id in allowed


def issue_session(user_id: int, secret: str, ttl: float = 604800.0) -> str:
    payload = json.dumps({"uid": user_id, "exp": time.time() + ttl}).encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def read_session(cookie: str | None, secret: str, now: float | None = None) -> int | None:
    """Return the signed-in user id, or None. Tolerates any garbage."""
    if not cookie or "." not in cookie:
        return None
    try:
        body, sig = cookie.split(".", 1)
        payload = _unb64(body)
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig)):
            return None
        data = json.loads(payload)
        if float(data["exp"]) < (now if now is not None else time.time()):
            return None
        return int(data["uid"])
    except Exception:
        return None


def session_secret(configured: str, bot_token: str) -> str:
    """Use the configured secret, or derive a stable one from the bot token.

    Deriving keeps setup to one fewer required value while still being
    unguessable, and it has a useful property: rotating the bot token
    invalidates every existing session.
    """
    if configured:
        return configured
    return hashlib.sha256(f"qalqon-web-session:{bot_token}".encode()).hexdigest()


def verify_access_token(supplied: str, configured: str) -> bool:
    """Token sign-in, for reaching the panel without a domain.

    Telegram's login widget validates the page's domain against the one
    registered with /setdomain, so it cannot work over an SSH tunnel or a bare
    IP. This is the alternative — and being a second way in, it is deliberately
    narrow:

      - OPT-IN. Disabled unless WEB_ACCESS_TOKEN is set. A default-on secondary
        credential is how panels end up unintentionally reachable.
      - Long. Rejects anything under 32 characters, so a memorable password
        cannot be used where the whole security argument rests on entropy.
      - Constant-time. A plain == leaks the matching prefix length, which is
        enough to recover a token one character at a time.

    Intended to be paired with binding the panel to 127.0.0.1, so that using it
    already requires SSH access to the host.
    """
    if not configured or len(configured) < 32:
        return False
    if not supplied:
        return False
    return hmac.compare_digest(str(supplied), str(configured))


# Sentinel user id recorded for a token sign-in. Negative so it can never
# collide with a real Telegram user id, and distinguishable in the logs from
# someone who signed in as a known person.
TOKEN_USER = -1
