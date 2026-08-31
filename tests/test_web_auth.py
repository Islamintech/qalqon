"""Dashboard authentication.

This is the only thing standing between the open internet and every moderation
record — including real users' message text. Anyone can POST anything to the
callback URL, so each check below is load-bearing and gets its own test.
"""
import re
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


# --- token sign-in (used when there is no domain for Telegram login) --------
from web.auth import TOKEN_USER, verify_access_token  # noqa: E402

GOOD = "x" * 48


def test_the_right_token_is_accepted():
    assert verify_access_token(GOOD, GOOD) is True


def test_a_wrong_token_is_rejected():
    assert verify_access_token("y" * 48, GOOD) is False


def test_a_prefix_of_the_token_is_rejected():
    """Constant-time comparison, so a partial match reveals nothing."""
    assert verify_access_token(GOOD[:40], GOOD) is False


def test_token_login_is_off_unless_configured():
    """A default-on second credential is how panels end up reachable."""
    assert verify_access_token("anything", "") is False
    assert verify_access_token("", "") is False


def test_a_short_token_is_refused_even_if_it_matches():
    """The whole security argument rests on entropy, so a memorable password
    must not be usable here."""
    assert verify_access_token("hunter2", "hunter2") is False
    assert verify_access_token("a" * 31, "a" * 31) is False
    assert verify_access_token("a" * 32, "a" * 32) is True


@pytest.mark.parametrize("supplied", ["", None, 0, [], {}])
def test_empty_supplied_values_never_pass(supplied):
    assert verify_access_token(supplied, GOOD) is False


def test_the_token_user_id_cannot_collide_with_a_real_one():
    """Telegram ids are positive, so a negative sentinel is unambiguous."""
    assert TOKEN_USER < 0


# --- the privacy notice is public -------------------------------------------
def test_privacy_page_needs_no_login():
    """A privacy notice behind a sign-in is not a notice. Telegram links to it
    from the bot's profile, where the reader has no account here."""
    from fastapi.testclient import TestClient

    from web.app import app

    with TestClient(app) as client:
        r = client.get("/privacy", follow_redirects=False)
    assert r.status_code == 200
    assert "Maxfiylik" in r.text


def test_privacy_page_states_the_configured_retention():
    """The figure is read from the live config, so the page cannot promise one
    thing while the bot does another."""
    from fastapi.testclient import TestClient

    from config import settings
    from web.app import app

    with TestClient(app) as client:
        body = client.get("/privacy").text
    if settings.event_retention_days:
        assert str(settings.event_retention_days) in body
    else:
        assert "muddatsiz" in body


# --- the public landing page ------------------------------------------------
def test_the_landing_page_is_public_and_indexable():
    """It is the URL people are given, so a stranger must not be bounced to a
    login box — and unlike every other page it carries no private data, so it
    is the only one allowed into search results."""
    from fastapi.testclient import TestClient

    from web.app import app

    with TestClient(app) as client:
        r = client.get("/", follow_redirects=False)
    assert r.status_code == 200
    assert "index,follow" in r.text
    assert "Qalqon" in r.text


def test_the_dashboard_is_still_behind_the_login():
    from fastapi.testclient import TestClient

    from web.app import app

    with TestClient(app) as client:
        for path in ("/app", "/groups", "/members", "/activity", "/usage"):
            r = client.get(path, follow_redirects=False)
            assert r.status_code == 303, path
            assert r.headers["location"] == "/login"


def test_the_landing_page_leaks_no_group_data():
    """Group names, member ids and message text belong to the communities
    being moderated. A portfolio page is the last place they should appear."""
    from fastapi.testclient import TestClient

    from web.app import app

    with TestClient(app) as client:
        body = client.get("/").text
    for leak in ("-100", "@islamun", "@vivora", "chat_id"):
        assert leak not in body, f"landing page leaked {leak}"


def test_the_landing_page_names_no_specific_community():
    """The product is general; which communities happen to use it is their
    business, not a marketing detail."""
    from fastapi.testclient import TestClient

    from web.app import app

    with TestClient(app) as client:
        body = client.get("/").text.lower()
    for term in ("uzbek", "korea", "so'm", "krw", "uzs"):
        assert term not in body, f"landing page names {term}"


# --- signed-in pages must actually render -----------------------------------
def _signed_in_client():
    """A client holding a valid session.

    The cookie is minted directly rather than by signing in, because the app
    reads WEB_ACCESS_TOKEN once at import: whether a token login works depends
    on which test imported web.app first, which made this flaky in the suite
    and green on its own.
    """
    from fastapi.testclient import TestClient

    from web import app as web_app
    from web.auth import issue_session

    client = TestClient(web_app.app)
    client.cookies.set(web_app.COOKIE, issue_session(1, web_app.SECRET))
    return client


@pytest.mark.parametrize("path", ["/app", "/groups", "/members", "/activity", "/usage"])
def test_every_dashboard_page_renders(path):
    """These were only ever checked for their redirect, so a template that
    raised — a renamed helper, say — passed the whole suite."""
    with _signed_in_client() as client:
        r = client.get(path)
    assert r.status_code == 200, path
    assert "<main>" in r.text


@pytest.mark.parametrize("path", ["/app", "/activity"])
def test_dashboard_html_tags_are_balanced(path):
    """A stray closing tag survived a bulk edit and shipped on every page."""
    with _signed_in_client() as client:
        body = client.get(path).text
    assert body.count("<main>") == body.count("</main>") == 1
    assert body.count("<div") == body.count("</div>"), "unbalanced <div>"


def test_the_dashboard_navigation_is_horizontal():
    """Five destinations do not justify a fixed column stealing a fifth of the
    width from the pages that need it most."""
    with _signed_in_client() as client:
        body = client.get("/app").text
    assert 'class="topbar"' in body
    assert "<aside" not in body


def test_the_layout_reflows_rather_than_only_shrinking():
    """A fixed-viewBox SVG scales its text down with its bars, so a chart that
    merely fits a phone is unreadable; and one-column tiles make a five-tile
    row taller than the screen. Both need explicit rules, not just max-width."""
    from web import render

    css = render.CSS
    assert ".chart{min-width:520px}" in css, "chart would shrink its own labels"
    assert "grid-template-columns:1fr 1fr" in css, "tiles collapse to one column"
    assert ".item .when{margin-left:0" in css, "timestamp still steals the row"
    breakpoints = sorted({int(w) for w in re.findall(r"max-width:(\d+)px", css)})
    assert len(breakpoints) >= 4, f"too few breakpoints: {breakpoints}"
