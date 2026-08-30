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
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402
from web import landing, pages, pricing, queries, render  # noqa: E402
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


def shell(body: str, user_id: int, active: str) -> HTMLResponse:
    """A signed-in page: sidebar + content."""
    label = "signed in with a token" if user_id == TOKEN_USER else f"ID {user_id}"
    return _document(
        f'<div class="shell">'
        f'{render.sidebar(active, settings.dry_run, label)}'
        f'<main>{body}</div></main></div>'
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
    desc = (
        "Qalqon is an anti-scam moderation bot for Telegram communities. It "
        "detects fraud across languages, removes clear attacks, and asks a "
        "human about the rest."
    )
    return HTMLResponse(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
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
        blocks.append(
            '<form method="post" action="/auth/token" style="margin-top:18px">'
            '<input class="field" type="password" name="token" '
            'placeholder="access token" autocomplete="current-password">'
            '<button class="btn" type="submit">Sign in</button></form>'
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
        f"<main class=login><div class=card><h1>Qalqon</h1>"
        f"<p>Only allow-listed admins can view this dashboard.</p>"
        f"{''.join(blocks)}</div></main>"
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
            "⚠️", "Cannot read the moderation database",
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
        landing.page(render.LOGO, signed_in=bool(_current_user(request))),
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

    The retention figure is read from the live configuration rather than
    written into the prose, so the page cannot claim one thing while the bot
    does another. If someone sets EVENT_RETENTION_DAYS=0, this page says so.
    """
    days = settings.event_retention_days
    if days:
        keep_uz = (
            f"Bu yozuvlar <b>{days} kundan</b> keyin avtomatik o'chiriladi."
        )
        keep_en = f"These records are deleted automatically after {days} days."
    else:
        keep_uz = (
            "Hozircha bu yozuvlar <b>muddatsiz</b> saqlanmoqda "
            "(EVENT_RETENTION_DAYS=0)."
        )
        keep_en = (
            "These records are currently kept <b>indefinitely</b> "
            "(EVENT_RETENTION_DAYS=0)."
        )

    body = f"""
<main style="max-width:720px">
<section>
<h2>Maxfiylik siyosati</h1>
<div class="card" style="line-height:1.65">

<p><b>Qalqon</b> — guruhlarni firibgarlik va spamdan himoya qiluvchi
moderator bot. Bu sahifada bot qanday ma'lumot saqlashi tushuntirilgan.</p>

<p><b>Nima saqlanadi.</b> Bot faqat o'zi chora ko'rgan holatlarni yozib
qo'yadi: guruh identifikatori, foydalanuvchi identifikatori va useri, qaror
(o'chirildi / bloklandi / ko'rib chiqilsin), qaror sababi va o'sha xabarning
dastlabki 500 belgisi. Bundan tashqari har bir a'zo uchun yuborilgan xabarlar
soni, ogohlantirishlar soni va holati (oddiy / ishonchli / bloklangan)
saqlanadi.</p>

<p><b>Nima saqlanmaydi.</b> Oddiy suhbat saqlanmaydi. Agar xabar shubhali
topilmasa, uning matni hech qayerga yozilmaydi. Bot shaxsiy xabarlarni
o'qimaydi, telefon raqami, manzil yoki to'lov ma'lumotlarini yig'maydi.</p>

<p><b>Qancha vaqt.</b> {keep_uz} Ogohlantirishlar
{settings.strike_decay_days} kundan keyin kuchini yo'qotadi.</p>

<p><b>Kim ko'radi.</b> Yozuvlarni faqat guruh adminlari va bot egasi ko'ra
oladi. Ma'lumot uchinchi shaxslarga sotilmaydi va berilmaydi.</p>

<p><b>Tashqi xizmatlar.</b> Xabar matni tahlil uchun
<a href="https://groq.com">Groq</a>ga, profil rasmi esa
<a href="https://huggingface.co">Hugging Face</a>ga yuboriladi. Ular bu
ma'lumotni faqat javob qaytarish uchun ishlatadi.</p>

<p><b>O'chirish.</b> O'zingiz haqingizdagi yozuvlarni o'chirishni so'rash
uchun guruh admini bilan bog'laning.</p>

<hr style="border:0;border-top:1px solid #242936;margin:22px 0">

<h3 style="font-size:14px;text-transform:none;letter-spacing:0;color:#a2a9b8">
English summary</h3>
<p class="dim" style="font-size:13px">Qalqon is an anti-scam moderation bot.
It records only the cases it acted on: the group and user id, the decision,
the reason, and the first 500 characters of the triggering message — plus each
member's message count, strikes and status. Ordinary conversation is never
stored. {keep_en} Strikes expire after {settings.strike_decay_days} days.
Records are visible only to group admins and the operator, and are never sold
or shared. Message text is sent to Groq for analysis and profile photos to
Hugging Face. To request deletion, contact your group admin.</p>

</div>
</section>
</div></main>"""
    return page(body, _current_user(request))


@app.get("/healthz")
async def healthz():
    """Unauthenticated on purpose: it reveals nothing and lets an uptime
    monitor check the panel itself."""
    return {"ok": True}
