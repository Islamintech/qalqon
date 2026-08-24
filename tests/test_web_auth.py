"""Dashboard authentication.

This is the only thing standing between the open internet and every moderation
record — including real users' message text. Anyone can POST anything to the
callback URL, so each check below is load-bearing and gets its own test.
"""
import hashlib
import hmac
import time

import pytest

from web.auth import (
    MAX_AUTH_AGE, is_allowed, issue_session, read_session, session_secret,
    verify_telegram_login,
)

TOKEN = "123456:test-bot-token"


def signed(**fields) -> dict:
    """Build a payload signed the way Telegram signs it."""
    fields.setdefault("id", 42)
    fields.setdefault("first_name", "Admin")
    fields.setdefault("auth_date", int(time.time()))
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(TOKEN.encode()).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return fields


# --- signature -------------------------------------------------------------
def test_a_genuine_login_is_accepted():
    assert verify_telegram_login(signed(), TOKEN) == 42


def test_a_forged_signature_is_rejected():
    payload = signed()
    payload["hash"] = "0" * 64
    assert verify_telegram_login(payload, TOKEN) is None


def test_tampering_with_the_user_id_invalidates_it():
    """The obvious attack: take your own valid login and change the id."""
    payload = signed(id=42)
    payload["id"] = 999
    assert verify_telegram_login(payload, TOKEN) is None


def test_a_payload_signed_with_another_token_is_rejected():
    payload = signed()
    assert verify_telegram_login(payload, "999:different-token") is None


def test_an_unsigned_payload_is_rejected():
    assert verify_telegram_login({"id": 42, "auth_date": time.time()}, TOKEN) is None


def test_extra_fields_are_covered_by_the_signature():
    """Telegram includes fields we may not know about; they must still be part
    of the checked string or they could be altered freely."""
    payload = signed(username="admin", photo_url="https://example/x.jpg")
    assert verify_telegram_login(payload, TOKEN) == 42
    payload["username"] = "someone_else"
    assert verify_telegram_login(payload, TOKEN) is None


# --- freshness -------------------------------------------------------------
def test_a_stale_login_is_rejected():
    """Without this, a login URL captured from browser history or a proxy log
    would work forever — the payload never changes."""
    old = signed(auth_date=int(time.time()) - MAX_AUTH_AGE - 60)
    assert verify_telegram_login(old, TOKEN) is None


def test_a_login_from_the_future_is_rejected():
    ahead = signed(auth_date=int(time.time()) + MAX_AUTH_AGE + 60)
    assert verify_telegram_login(ahead, TOKEN) is None


def test_a_recent_login_is_fine():
    assert verify_telegram_login(signed(auth_date=int(time.time()) - 30), TOKEN) == 42


# --- malformed input -------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [{}, {"hash": "x"}, {"id": "abc", "auth_date": "now", "hash": "x"}, {"id": None}],
)
def test_garbage_never_raises(payload):
    """This is fed straight from a query string."""
    assert verify_telegram_login(payload, TOKEN) is None


def test_no_bot_token_means_no_login():
    assert verify_telegram_login(signed(), "") is None


# --- the allow-list --------------------------------------------------------
def test_a_valid_login_is_not_authorisation():
    """Anyone in the world can press the login button and get a valid
    signature. The allow-list is what makes them an admin."""
    assert verify_telegram_login(signed(id=777), TOKEN) == 777
    assert is_allowed(777, {42}) is False


def test_an_empty_allowlist_denies_everyone():
    """Defaulting to open would mean a forgotten config value silently
    publishes every moderation record."""
    assert is_allowed(42, set()) is False


def test_an_allowlisted_user_passes():
    assert is_allowed(42, {42, 43}) is True


# --- sessions --------------------------------------------------------------
def test_a_session_round_trips():
    secret = "s3cret"
    assert read_session(issue_session(42, secret), secret) == 42


def test_a_session_signed_with_another_secret_is_rejected():
    assert read_session(issue_session(42, "one"), "two") is None


def test_a_tampered_session_is_rejected():
    secret = "s3cret"
    cookie = issue_session(42, secret)
    body, sig = cookie.split(".", 1)
    assert read_session(f"{body}x.{sig}", secret) is None


def test_an_expired_session_is_rejected():
    secret = "s3cret"
    cookie = issue_session(42, secret, ttl=-1)
    assert read_session(cookie, secret) is None


@pytest.mark.parametrize("cookie", [None, "", "garbage", "a.b", "...", "x" * 500])
def test_a_malformed_cookie_never_raises(cookie):
    assert read_session(cookie, "s3cret") is None


def test_the_derived_secret_is_stable_and_token_bound():
    a = session_secret("", TOKEN)
    assert a == session_secret("", TOKEN), "must survive a restart"
    assert a != session_secret("", "999:other"), "rotating the token logs everyone out"
    assert session_secret("explicit", TOKEN) == "explicit"
