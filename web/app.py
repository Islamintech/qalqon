"""Read-only moderation dashboard.

Runs as its OWN process, separate from the bot, and opens the database
read-only. Two reasons that separation is deliberate:

  - a bug or compromise in the web layer cannot corrupt moderation state
  - the panel can crash, or be restarted, without interrupting moderation

Everything is server-rendered with inline CSS and no JavaScript. A dashboard
that depends on a CDN breaks when the CDN does, leaks visitor data to a third
party, and needs a looser CSP — none of which a page showing private group
messages should accept.

PRIVACY: this renders real users' message text. That is necessary for judging
whether a flag was a false positive, but it means the panel is as sensitive as
the groups it watches. Serve it over HTTPS, keep the allow-list tight.
"""
import html
import logging
import os
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402
from models import store  # noqa: E402
from web import landing, pages, pricing, queries, render  # noqa: E402
from web import privacy as privacy_page  # noqa: E402
from web.auth import (  # noqa: E402
    TOKEN_USER, is_allowed, issue_session, read_session, session_secret,
    verify_access_token, verify_telegram_login,
)

# uvicorn configures its own loggers but not ours, so without this every
# INFO record from the app is dropped — including successful sign-ins. On a
# panel that renders private group messages, "who looked, and when" is the one
# audit trail worth having, and silence is indistinguishable from nobody
# looking.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("qalqon.web")
app = FastAPI(title="Qalqon", docs_url=None, redoc_url=None, openapi_url=None)

COOKIE = "qalqon_session"
SECRET = session_secret(settings.web_session_secret, settings.telegram_token)
ALLOWED = settings.web_admin_ids


def _current_user(request: Request) -> int | None:
    return read_session(request.cookies.get(COOKIE), SECRET)


def _ago(ts: float | None) -> str:
    if not ts:
        return "never"
    seconds = int(max(time.time() - ts, 0))
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def e(value) -> str:
    """Escape everything. Usernames, reasons and message text are all attacker-
    controlled — a group member choosing a name with a <script> tag in it must
    not be able to run code in an admin's browser."""
    return html.escape(str(value if value is not None else ""), quote=True)


THEME_COOKIE = "qalqon_theme"
THEMES = {"light", "dark"}

# The chosen theme has to reach _document(), which every page funnels through
# and which has no Request. Threading it through a dozen call sites would put
# a parameter nobody reads into every signature, so it rides a context
# variable set once per request instead.
_theme: ContextVar[str] = ContextVar("theme", default="")
_here: ContextVar[str] = ContextVar("here", default="/")


@app.middleware("http")
async def _remember_theme(request: Request, call_next):
    chosen = request.cookies.get(THEME_COOKIE, "")
    tok_t = _theme.set(chosen if chosen in THEMES else "")
    here = request.url.path
    if request.url.query:
        here = f"{here}?{request.url.query}"
    tok_h = _here.set(here)
    try:
        return await call_next(request)
    finally:
        _theme.reset(tok_t)
        _here.reset(tok_h)


@app.get("/theme")
async def set_theme(v: str = "auto", next: str = "/"):
    """Store the choice and go back where the reader was.

    `next` comes off a URL, so it is only ever used when it is a path on this
    site: a bare '/foo'. Anything else — an absolute URL, a protocol-relative
    '//host' — would make this an open redirect.
    """
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    if v in THEMES:
        response.set_cookie(
            THEME_COOKIE, v, max_age=31536000, path="/",
            samesite="lax", httponly=False,
        )
    else:
        response.delete_cookie(THEME_COOKIE, path="/")
    return response


def shell(body: str, user_id: int, active: str) -> HTMLResponse:
    """A signed-in page: top bar + content."""
    label = "signed in with a token" if user_id == TOKEN_USER else f"ID {user_id}"
    return _document(
        f'<div class="shell">'
        f"{render.topbar(active, settings.dry_run, label, _theme.get(), quote(_here.get(), safe='/?=&'))}"
        f"<main>{body}</main>"
        f"</div>"
    )


def page(body: str, user_id: int | None = None) -> HTMLResponse:
    """A page with no sidebar — login, errors, and the public privacy notice."""
    return _document(body)


def _document(inner: str, extra_css: str = "", public: bool = False) -> HTMLResponse:
    # The landing page is the only thing meant to be found; every other page
    # renders private group data and stays out of search results.
    robots = (
        "index,follow" if public
        else "noindex,nofollow"
    )
    # An explicit choice is stamped on the root element; "auto" stamps nothing
    # and leaves the media query in charge.
    chosen = _theme.get()
    theme_attr = f' data-theme="{chosen}"' if chosen in THEMES else ""
    desc = (
        "Qalqon is an anti-scam moderation bot for Telegram communities. It "
        "detects fraud across languages, removes clear attacks, and asks a "
        "human about the rest."
    )
    return HTMLResponse(
        f"<!doctype html><html lang=en{theme_attr}>"
        "<head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
        '<link rel="mask-icon" href="/favicon.svg" color="#3987e5">'
        "<meta name='theme-color' content='#3987e5'>"
        f"<meta name=robots content='{robots}'>"
        f'<meta name="description" content="{desc}">'
        '<meta property="og:title" content="Qalqon — anti-scam moderation for Telegram">'
        f'<meta property="og:description" content="{desc}">'
        '<meta property="og:type" content="website">'
        "<title>Qalqon — anti-scam moderation for Telegram</title>"
        f"<style>{render.CSS}{extra_css}</style></head><body>{inner}</body></html>"
    )


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    if _current_user(request):
        return RedirectResponse("/app", status_code=303)
    blocks = []
    if settings.web_bot_username:
        blocks.append(
            '<script async src="https://telegram.org/js/telegram-widget.js?22" '
            f'data-telegram-login="{e(settings.web_bot_username)}" data-size="large" '
            f'data-auth-url="{e(settings.web_base_url)}/auth/telegram" '
            'data-request-access="write"></script>'
        )
    if settings.web_access_token:
        # Only draw the divider when there is something above it to divide.
        rule = '<div class="or"><span>or</span></div>' if blocks else ""
        blocks.append(
            f'{rule}<form method="post" action="/auth/token">'
            '<label class="lbl" for="tok">Access token</label>'
            '<input class="field" id="tok" type="password" name="token" '
            'placeholder="••••••••••••••••" autocomplete="current-password">'
            '<button class="btn" type="submit">Continue</button></form>'
        )
    if not blocks:
        return page(
            "<main class=login><div class=card><h1>Setup needed</h1><p>No sign-in "
            "method is configured. Either set <code>WEB_BOT_USERNAME</code> and "
            "register the domain with <code>/setdomain</code> in @BotFather, or "
            "set <code>WEB_ACCESS_TOKEN</code> (32+ characters) to sign in with "
            "a token instead.</p></div></main>"
        )
    return page(
        f"<main class=login><div class=card><h1>Sign in to the dashboard</h1>"
        f"<p>Only the administrators of a watched group can open it.</p>"
        f"{''.join(blocks)}</div>"
        f'<p class="foot">The dashboard is read-only. Moderation decisions are '
        f"reviewed from Telegram, where the alert arrives.</p></main>"
    )


@app.post("/auth/token")
async def auth_token(request: Request):
    form = await request.form()
    if not verify_access_token(form.get("token", ""), settings.web_access_token):
        log.warning("dashboard token sign-in REJECTED from %s", request.client.host)
        return page("<main class=login><div class=card><h1>Sign-in failed</h1>"
                    "<p>That token is not valid. "
                    "<a href='/login'>Try again</a>.</p></div></main>")
    response = RedirectResponse("/app", status_code=303)
    response.set_cookie(
        COOKIE, issue_session(TOKEN_USER, SECRET),
        httponly=True, samesite="lax",
        secure=settings.web_base_url.startswith("https"),
        max_age=604800,
    )
    log.info("dashboard token sign-in from %s", request.client.host)
    return response


@app.get("/auth/telegram")
async def auth_telegram(request: Request):
    data = dict(request.query_params)
    user_id = verify_telegram_login(data, settings.telegram_token)
    if user_id is None:
        return page("<main class=login><div class=card><h1>Sign-in failed</h1>"
                    "<p>That login could not be verified, or it "
                    "expired. <a href='/login'>Try again</a>.</p></div></main>")
    if not is_allowed(user_id, ALLOWED):
        # Deliberately says who you are: the usual reason for this is an admin
        # not having added their own id yet, and hiding it just wastes time.
        log.warning("denied dashboard access to telegram user %s", user_id)
        return page(
            f"<main class=login><div class=card><h1>Not authorised</h1><p>Telegram "
            f"user <code>{user_id}</code> is not on the allow-list. Add it to "
            f"<code>WEB_ADMIN_IDS</code> and restart the panel.</p></div></main>"
        )
    response = RedirectResponse("/app", status_code=303)
    response.set_cookie(
        COOKIE, issue_session(user_id, SECRET),
        httponly=True, samesite="lax",
        secure=settings.web_base_url.startswith("https"),
        max_age=604800,
    )
    log.info("dashboard sign-in by telegram user %s", user_id)
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


def _load(request: Request):
    """Everything the pages need, in one read-only pass.

    One loader for all four pages rather than per-page queries: the dataset is
    tiny, and it keeps the filter semantics identical everywhere — a period or
    group chosen on one page means the same thing on the next.
    """
    try:
        days = int(request.query_params.get("days", 14))
    except ValueError:
        days = 14
    days = days if days in (7, 14, 30) else 14
    raw = request.query_params.get("chat", "")
    chat_id = int(raw) if raw.lstrip("-").isdigit() else None

    def link(days_v=None, chat_v="keep"):
        params = {"days": days_v if days_v is not None else days}
        target = chat_id if chat_v == "keep" else chat_v
        if target is not None:
            params["chat"] = target
        return f"{request.url.path}?" + "&".join(f"{k}={v}" for k, v in params.items())

    conn = queries.connect(settings.db_path)
    try:
        return {
            "days": days, "chat_id": chat_id, "link": link,
            "ov": queries.overview(conn, chat_id),
            "acc": queries.accuracy(conn, chat_id),
            "daily": queries.daily_activity(conn, chat_id, days=days),
            "chats": queries.per_chat(conn),
            "events": queries.recent_events(conn, chat_id),
            "offenders": queries.top_offenders(conn, chat_id),
            "health": queries.health(conn),
            "usage": queries.usage_summary(conn, chat_id, days=days),
            "usage_daily": queries.usage_daily(conn, chat_id, days=days),
            "usage_by_chat": queries.usage_by_chat(conn, days=days),
            "peak": queries.busiest_minute(conn, days=days),
            "prices": pricing.fetch(settings.groq_api_key),
            "model": settings.groq_model,
            "token_limit": settings.groq_token_limit_per_minute,
            "billed": settings.groq_plan == "paid",
        }
    finally:
        conn.close()


def _guard(request: Request):
    """Returns (user_id, None) when signed in, or (None, response) when not."""
    user_id = _current_user(request)
    if not user_id:
        return None, RedirectResponse("/login", status_code=303)
    return user_id, None


def _db_error(user_id, exc) -> HTMLResponse:
    return shell(
        pages.head("Database unavailable")
        + render.empty(
            "warn", "Cannot read the moderation database",
            f"{pages.e(exc)} — expected at {pages.e(settings.db_path)}. "
            "The dashboard opens it read-only, so the bot must have created "
            "it first.",
        ), user_id, "/app",
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Public. The URL people are given, so it explains the project rather
    than bouncing a stranger to a login box."""
    return _document(
        landing.page(render.LOGO, signed_in=bool(_current_user(request)),
                     theme=_theme.get(),
                     here=quote(_here.get(), safe="/?=&")),
        extra_css=landing.CSS, public=True,
    )


@app.get("/app", response_class=HTMLResponse)
async def overview(request: Request):
    user_id, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        data = _load(request)
    except Exception as exc:
        return _db_error(user_id, exc)
    return shell(pages.overview(data), user_id, "/app")


@app.get("/groups", response_class=HTMLResponse)
async def groups(request: Request):
    user_id, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        data = _load(request)
    except Exception as exc:
        return _db_error(user_id, exc)
    return shell(pages.groups(data), user_id, "/groups")


@app.get("/members", response_class=HTMLResponse)
async def members(request: Request):
    user_id, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        data = _load(request)
    except Exception as exc:
        return _db_error(user_id, exc)
    return shell(pages.members(data), user_id, "/members")


@app.get("/activity", response_class=HTMLResponse)
async def activity(request: Request):
    user_id, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        data = _load(request)
    except Exception as exc:
        return _db_error(user_id, exc)
    return shell(pages.activity(data), user_id, "/activity")


@app.get("/usage", response_class=HTMLResponse)
async def usage(request: Request):
    user_id, redirect = _guard(request)
    if redirect:
        return redirect
    try:
        data = _load(request)
    except Exception as exc:
        return _db_error(user_id, exc)
    return shell(pages.usage(data), user_id, "/usage")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    """Public — no sign-in. A privacy notice behind a login is not a notice.

    Every figure is read from the live configuration rather than written into
    the prose, so the page cannot claim one thing while the bot does another.
    If someone sets EVENT_RETENTION_DAYS=0, this page says so.

    It is `public=True`: Telegram links here from the bot's profile, and unlike
    the rest of web/ the page carries no group data, so it belongs in search
    results alongside the landing page.
    """
    return _document(
        privacy_page.page(
            render.LOGO,
            signed_in=bool(_current_user(request)),
            theme=_theme.get(),
            here=quote(_here.get(), safe="/?=&"),
            retention_days=settings.event_retention_days,
            strike_days=settings.strike_decay_days,
            snippet_chars=store.SNIPPET_CHARS,
        ),
        extra_css=landing.CSS + privacy_page.CSS,
        public=True,
    )


@app.get("/favicon.svg")
async def favicon():
    """The mark, standalone. An SVG icon cannot reach the stylesheet, so its
    two colours are literal rather than theme tokens."""
    return Response(
        render.FAVICON,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/healthz")
async def healthz():
    """Unauthenticated on purpose: it reveals nothing and lets an uptime
    monitor check the panel itself."""
    return {"ok": True}
