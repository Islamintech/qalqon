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
from web import queries  # noqa: E402
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
log = logging.getLogger("scamguard.web")
app = FastAPI(title="ScamGuard", docs_url=None, redoc_url=None, openapi_url=None)

COOKIE = "scamguard_session"
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


CSS = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
 background:#0f1115;color:#e6e8ee}
a{color:#7aa2f7}
header{padding:18px 24px;border-bottom:1px solid #232734;display:flex;
 align-items:center;gap:16px;flex-wrap:wrap}
h1{font-size:18px;margin:0;font-weight:600}
.badge{padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600}
.live{background:#3d1d1d;color:#ff9d9d}
.dry{background:#16301f;color:#8ee0a8}
.muted{color:#8b90a0}
main{padding:24px;max-width:1200px;margin:0 auto}
section{margin-bottom:34px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:#8b90a0;
 margin:0 0 12px;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:#171a21;border:1px solid #232734;border-radius:10px;padding:14px 16px}
.card .n{font-size:26px;font-weight:650;letter-spacing:-.02em}
.card .l{font-size:12px;color:#8b90a0;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#8b90a0;font-weight:600;padding:8px 10px;
 border-bottom:1px solid #232734;font-size:12px}
td{padding:8px 10px;border-bottom:1px solid #1b1f28;vertical-align:top}
tr:hover td{background:#141821}
.tag{padding:2px 7px;border-radius:5px;font-size:11px;font-weight:600;
 white-space:nowrap;display:inline-block}
.BAN{background:#3d1d1d;color:#ff9d9d}
.DELETE{background:#3a2d17;color:#f3c07b}
.REVIEW{background:#1d2e3d;color:#8fc6ff}
.ADMIN_IGNORE,.ADMIN_UNBAN,.ADMIN_WHITELIST{background:#2a2140;color:#c3a6ff}
.ADMIN_BAN{background:#3d1d1d;color:#ff9d9d}
.chart{display:flex;align-items:flex-end;gap:3px;height:130px;
 background:#171a21;border:1px solid #232734;border-radius:10px;padding:12px}
.col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:1px;
 min-width:0}
.bar{width:100%;border-radius:2px 2px 0 0}
.bar.BAN{background:#e06c6c}.bar.DELETE{background:#d9a441}.bar.REVIEW{background:#5b9bd5}
.col span{font-size:9px;color:#6b7080;text-align:center;margin-top:5px;
 overflow:hidden;white-space:nowrap}
.note{background:#171a21;border-left:3px solid #d9a441;padding:10px 14px;
 border-radius:0 8px 8px 0;font-size:13px;color:#b8bdcc;margin-top:10px}
.msg{color:#9aa0b0;font-size:12px;max-width:420px;overflow-wrap:anywhere}
.login{max-width:420px;margin:14vh auto;text-align:center;padding:0 20px}
code{background:#171a21;padding:2px 6px;border-radius:4px;font-size:12px}
"""


def page(body: str, user_id: int | None = None) -> HTMLResponse:
    mode = "LIVE" if not settings.dry_run else "DRY-RUN"
    cls = "live" if not settings.dry_run else "dry"
    label = "token" if user_id == TOKEN_USER else user_id
    who = (
        f'<span class="muted">signed in as {e(label)} · '
        f'<a href="/logout">sign out</a></span>'
        if user_id else ""
    )
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>ScamGuard</title><style>{CSS}</style></head><body>"
        f"<header><h1>🛡️ ScamGuard</h1>"
        f"<span class='badge {cls}'>{mode}</span>"
        f"<span class='muted'>autonomy: {e(settings.autonomy)}</span>"
        f"<div style='flex:1'></div>{who}</header>{body}</body></html>"
    )


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    if _current_user(request):
        return RedirectResponse("/", status_code=303)
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
            '<input type="password" name="token" placeholder="access token" '
            'autocomplete="current-password" style="width:100%;padding:10px;'
            'border-radius:8px;border:1px solid #232734;background:#171a21;'
            'color:#e6e8ee;font-size:14px">'
            '<button type="submit" style="margin-top:10px;width:100%;padding:10px;'
            'border-radius:8px;border:0;background:#2f4f8f;color:#fff;'
            'font-size:14px;font-weight:600;cursor:pointer">Sign in</button></form>'
        )
    if not blocks:
        return page(
            "<main class=login><h2>Setup needed</h2><p class=muted>No sign-in "
            "method is configured. Either set <code>WEB_BOT_USERNAME</code> and "
            "register the domain with <code>/setdomain</code> in @BotFather, or "
            "set <code>WEB_ACCESS_TOKEN</code> (32+ characters) to sign in with "
            "a token instead.</p></main>"
        )
    return page(
        f"<main class=login><h2>Sign in</h2>"
        f"<p class=muted>Only allow-listed admins can view this.</p>"
        f"{''.join(blocks)}</main>"
    )


@app.post("/auth/token")
async def auth_token(request: Request):
    form = await request.form()
    if not verify_access_token(form.get("token", ""), settings.web_access_token):
        log.warning("dashboard token sign-in REJECTED from %s", request.client.host)
        return page("<main class=login><h2>Sign-in failed</h2>"
                    "<p class=muted>That token is not valid. "
                    "<a href='/login'>Try again</a>.</p></main>")
    response = RedirectResponse("/", status_code=303)
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
        return page("<main class=login><h2>Sign-in failed</h2>"
                    "<p class=muted>That login could not be verified, or it "
                    "expired. <a href='/login'>Try again</a>.</p></main>")
    if not is_allowed(user_id, ALLOWED):
        # Deliberately says who you are: the usual reason for this is an admin
        # not having added their own id yet, and hiding it just wastes time.
        log.warning("denied dashboard access to telegram user %s", user_id)
        return page(
            f"<main class=login><h2>Not authorised</h2><p class=muted>Telegram "
            f"user <code>{user_id}</code> is not on the allow-list. Add it to "
            f"<code>WEB_ADMIN_IDS</code> and restart the panel.</p></main>"
        )
    response = RedirectResponse("/", status_code=303)
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


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user_id = _current_user(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    try:
        conn = queries.connect(settings.db_path)
    except Exception as exc:
        return page(
            f"<main><h2>Database unavailable</h2><p class=muted>{e(exc)}</p>"
            f"<p class=muted>Expected at <code>{e(settings.db_path)}</code>. The "
            f"panel opens it read-only, so it must already exist — start the bot "
            f"once first.</p></main>", user_id,
        )
    try:
        ov = queries.overview(conn)
        acc = queries.accuracy(conn)
        daily = queries.daily_activity(conn)
        chats = queries.per_chat(conn)
        events = queries.recent_events(conn)
        offenders = queries.top_offenders(conn)
        hp = queries.health(conn)
    finally:
        conn.close()

    cards = "".join(
        f"<div class=card><div class=n>{v}</div><div class=l>{k}</div></div>"
        for k, v in (
            ("groups", len(chats)),
            ("known users", ov["users"]),
            ("messages seen", ov["messages_seen"]),
            ("active strikes", ov["active_strikes"]),
            ("banned", ov["banned"]),
            ("whitelisted", ov["whitelisted"]),
        )
    )

    peak = max(
        (d["REVIEW"] + d["DELETE"] + d["BAN"] for d in daily), default=0
    ) or 1
    bars = ""
    for d in daily:
        segs = "".join(
            f"<div class='bar {a}' style='height:{d[a] / peak * 100:.1f}px'></div>"
            for a in ("BAN", "DELETE", "REVIEW") if d[a]
        )
        bars += f"<div class=col>{segs}<span>{d['day'][5:]}</span></div>"

    rate = acc["overturn_rate"]
    rate_text = f"{rate * 100:.0f}%" if rate is not None else "—"
    accuracy_block = (
        f"<div class=cards>"
        f"<div class=card><div class=n>{acc['bot_actions']}</div>"
        f"<div class=l>bot decisions</div></div>"
        f"<div class=card><div class=n>{acc['reviewed']}</div>"
        f"<div class=l>reviewed by a human</div></div>"
        f"<div class=card><div class=n>{acc['overturned']}</div>"
        f"<div class=l>overturned</div></div>"
        f"<div class=card><div class=n>{rate_text}</div>"
        f"<div class=l>overturn rate</div></div></div>"
        f"<div class=note><strong>Read this as an upper bound, not a "
        f"measurement.</strong> Only {acc['reviewed']} of {acc['bot_actions']} "
        f"decisions were reviewed, and nobody taps a button on the obviously "
        f"correct ones — so the sample is biased toward mistakes. It is "
        f"directional evidence about your thresholds, not a false-positive "
        f"rate.</div>"
    )

    chat_rows = "".join(
        f"<tr><td><code>{c['chat_id']}</code></td><td>{c['users']}</td>"
        f"<td><span class='tag BAN'>{c['bans'] or 0}</span></td>"
        f"<td><span class='tag DELETE'>{c['deletes'] or 0}</span></td>"
        f"<td><span class='tag REVIEW'>{c['reviews'] or 0}</span></td>"
        f"<td class=muted>{_ago(c['last'])}</td></tr>"
        for c in chats
    ) or "<tr><td colspan=6 class=muted>no activity yet</td></tr>"

    event_rows = "".join(
        f"<tr><td class=muted>{_when(ev['ts'])}</td>"
        f"<td><span class='tag {e(ev['action'])}'>{e(ev['action'])}</span></td>"
        f"<td>{'@' + e(ev['username']) if ev['username'] else e(ev['user_id'])}</td>"
        f"<td class=muted><code>{ev['chat_id']}</code></td>"
        f"<td class=msg>{e(ev['reason'])}</td>"
        f"<td class=msg>{e(ev['text'])}</td></tr>"
        for ev in events
    ) or "<tr><td colspan=6 class=muted>nothing recorded yet</td></tr>"

    offender_rows = "".join(
        f"<tr><td>{'@' + e(o['username']) if o['username'] else e(o['user_id'])}</td>"
        f"<td class=muted><code>{o['chat_id']}</code></td>"
        f"<td>{o['lifetime']}</td><td>{o['messages_seen']}</td>"
        f"<td class=muted>{e(o['status'])}</td></tr>"
        for o in offenders
    ) or "<tr><td colspan=5 class=muted>nobody has a strike</td></tr>"

    return page(
        f"<main>"
        f"<section><h2>Overview</h2><div class=cards>{cards}</div>"
        f"<p class=muted style='margin-top:10px'>last moderation event "
        f"{_ago(hp['last_event'])} · this is not a liveness check — a quiet "
        f"chat also produces nothing. Trust the heartbeat for that.</p></section>"
        f"<section><h2>Last 14 days</h2><div class=chart>{bars}</div></section>"
        f"<section><h2>Is it getting it right?</h2>{accuracy_block}</section>"
        f"<section><h2>Groups</h2><table><tr><th>chat</th><th>users</th>"
        f"<th>bans</th><th>deletes</th><th>reviews</th><th>last</th></tr>"
        f"{chat_rows}</table></section>"
        f"<section><h2>Most strikes</h2><table><tr><th>user</th><th>chat</th>"
        f"<th>lifetime strikes</th><th>messages</th><th>status</th></tr>"
        f"{offender_rows}</table></section>"
        f"<section><h2>Recent decisions</h2><table><tr><th>when (UTC)</th>"
        f"<th>action</th><th>user</th><th>chat</th><th>why</th><th>message</th></tr>"
        f"{event_rows}</table></section>"
        f"</main>",
        user_id,
    )


@app.get("/healthz")
async def healthz():
    """Unauthenticated on purpose: it reveals nothing and lets an uptime
    monitor check the panel itself."""
    return {"ok": True}
