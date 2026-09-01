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


def test_the_landing_page_test_count_is_not_stale(request):
    """The landing page claims a number of automated tests. A claim about the
    project that only a human remembers to update is a claim that goes wrong
    quietly, so the suite counts itself."""
    collected = len(request.session.items)
    if collected < 300:
        pytest.skip("a subset of the suite was run; the total is not knowable")
    from web import landing, render

    html = landing.page(render.LOGO, signed_in=False)
    assert f"<b>{collected}</b><span>automated tests</span>" in html, (
        f"the landing page states a different number; the suite has {collected}"
    )


def test_the_two_stylesheets_do_not_define_the_same_class():
    """render.CSS and landing.CSS are both served on every page, so a class
    named in both silently applies the wrong rules to the wrong element.

    This is not hypothetical: the landing hero was `class="hero"`, and the
    dashboard's `.hero` card rule (display:flex; align-items:center) turned the
    eyebrow, headline, paragraph, buttons and stats into five flex items in one
    row. The landing's `.note` captions were separately picking up the
    dashboard's amber warning background.
    """
    import re

    from web import landing, render

    def unscoped(css):
        found = set()
        for selector in re.findall(r"^([.#][^{@]*)\{", css, re.M):
            for part in selector.split(","):
                part = part.strip()
                if re.fullmatch(r"\.[a-zA-Z][\w-]*", part):
                    found.add(part)
        return found

    shared = unscoped(render.CSS) & unscoped(landing.CSS)
    assert not shared, f"defined in both stylesheets: {sorted(shared)}"


# --- the colour theme -------------------------------------------------------

def _client():
    from fastapi.testclient import TestClient

    from web import app as web_app

    return TestClient(web_app.app)


def _html_tag(text: str) -> str:
    """Just the <html ...> tag: the stylesheet mentions data-theme too."""
    return text[text.index("<html"):text.index(">", text.index("<html")) + 1]


def test_the_theme_defaults_to_the_system_setting():
    """No cookie means no data-theme attribute, so the media query decides."""
    r = _client().get("/")
    assert "data-theme" not in _html_tag(r.text)
    assert "prefers-color-scheme:dark" in r.text


@pytest.mark.parametrize("choice", ["light", "dark"])
def test_choosing_a_theme_stamps_it_on_the_page(choice):
    with _client() as client:
        client.get(f"/theme?v={choice}&next=/", follow_redirects=False)
        r = client.get("/")
    assert f'<html lang=en data-theme="{choice}">' in r.text


def test_an_unrecognised_value_clears_the_choice():
    """There is no longer a control for it, but the route still falls back to
    the operating system rather than storing something meaningless."""
    with _client() as client:
        client.get("/theme?v=dark&next=/", follow_redirects=False)
        client.get("/theme?v=sepia&next=/", follow_redirects=False)
        r = client.get("/")
    assert "data-theme" not in _html_tag(r.text)


def test_an_unknown_theme_is_ignored_rather_than_stamped():
    with _client() as client:
        client.get("/theme?v=<script>&next=/", follow_redirects=False)
        r = client.get("/")
    assert "data-theme" not in _html_tag(r.text)


@pytest.mark.parametrize("hostile", [
    "https://evil.example/",     # absolute
    "//evil.example/",           # protocol-relative
    "javascript:alert(1)",
])
def test_the_theme_switch_cannot_be_used_as_an_open_redirect(hostile):
    """`next` comes off a URL anyone can hand a signed-in admin."""
    r = _client().get(f"/theme?v=dark&next={hostile}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_the_switch_offers_light_and_dark_and_marks_the_current_one():
    from web import render

    html = render.theme_switch("dark", "/activity")
    assert "/theme?v=light" in html and "/theme?v=dark" in html
    assert "/theme?v=auto" not in html
    assert html.count('aria-current="true"') == 1
    assert 'href="/theme?v=dark&amp;next=/activity"' in html


def test_before_a_choice_is_made_the_css_marks_the_current_one():
    """The server cannot read a media query, so with no cookie it does not know
    which palette is on screen; the switch defers to CSS instead of guessing."""
    from web import render

    html = render.theme_switch("", "/app")
    assert 'class="theme auto"' in html
    assert "on" not in html.split("<a")[0]
    assert ".theme.auto .seg.dark{background:var(--accent-soft)" in render.CSS


def test_both_palettes_define_every_token():
    """A token defined in one palette and not the other renders as an empty
    value — an invisible element rather than a loud failure."""
    import re

    from web import render

    names = lambda block: set(re.findall(r"(--[\w-]+):", block))
    assert names(render.LIGHT) == names(render.DARK)


# --- the mark ---------------------------------------------------------------

def test_the_favicon_is_served_and_stands_alone():
    """A tab icon never sees the stylesheet, so it cannot use theme tokens."""
    r = _client().get("/favicon.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "var(--" not in r.text, "a CSS variable would render as no colour"
    assert "xmlns" in r.text, "a standalone SVG needs its namespace"


def test_every_page_points_at_the_favicon():
    from web import render

    with _signed_in_client() as client:
        pages = [client.get(p).text for p in ("/app", "/activity")]
    pages.append(_client().get("/").text)
    for html in pages:
        assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' in html
    assert "class=\"mark\"" in render.LOGO


def test_the_mark_is_never_stretched():
    """One glyph, one aspect ratio: the SVG carries no width/height of its own
    and both headers size it by height with width:auto."""
    import re

    from web import landing, render

    assert "width=" not in render.LOGO.split(">")[0]
    assert "height=" not in render.LOGO.split(">")[0]
    for css, selector in ((render.CSS, ".brand .mark"),
                          (landing.CSS, ".lp-brand .mark")):
        rule = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
        assert rule, selector
        assert "width:auto" in rule.group(1), selector
        assert re.search(r"height:\d+px", rule.group(1)), selector
