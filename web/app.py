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
from web import queries, render  # noqa: E402
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


def page(body: str, user_id: int | None = None) -> HTMLResponse:
    mode = "LIVE" if not settings.dry_run else "DRY-RUN"
    cls = "live" if not settings.dry_run else "dry"
    label = "token" if user_id == TOKEN_USER else user_id
    who = (
        f'<span class="who">{e(label)} · <a href="/logout">sign out</a></span>'
        if user_id else ""
    )
    return HTMLResponse(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<meta name=robots content='noindex,nofollow'>"
        "<title>Qalqon</title>"
        f"<style>{render.CSS}</style></head><body>"
        f'<header><span class="brand">{render.LOGO} Qalqon</span>'
        f'<span class="badge {cls}">{mode}</span>'
        f'<span class="sub">{e(settings.autonomy)}</span>'
        f'<span class="spacer"></span>{who}</header>{body}'
        f'<footer style="padding:24px 22px 40px;text-align:center;'
        f'font-size:12px;color:#6f7688">Qalqon &middot; '
        f'<a href="/privacy">Maxfiylik siyosati</a></footer>'
        f'</body></html>'
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
            '<input class="field" type="password" name="token" '
            'placeholder="access token" autocomplete="current-password">'
            '<button class="btn" type="submit">Sign in</button></form>'
        )
    if not blocks:
        return page(
            "<main class=login><h2>Setup needed</h2><p>No sign-in "
            "method is configured. Either set <code>WEB_BOT_USERNAME</code> and "
            "register the domain with <code>/setdomain</code> in @BotFather, or "
            "set <code>WEB_ACCESS_TOKEN</code> (32+ characters) to sign in with "
            "a token instead.</p></main>"
        )
    return page(
        f"<main class=login><h2>Sign in</h2>"
        f"<p>Only allow-listed admins can view this.</p>"
        f"{''.join(blocks)}</main>"
    )


@app.post("/auth/token")
async def auth_token(request: Request):
    form = await request.form()
    if not verify_access_token(form.get("token", ""), settings.web_access_token):
        log.warning("dashboard token sign-in REJECTED from %s", request.client.host)
        return page("<main class=login><h2>Sign-in failed</h2>"
                    "<p>That token is not valid. "
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
                    "<p>That login could not be verified, or it "
                    "expired. <a href='/login'>Try again</a>.</p></main>")
    if not is_allowed(user_id, ALLOWED):
        # Deliberately says who you are: the usual reason for this is an admin
        # not having added their own id yet, and hiding it just wastes time.
        log.warning("denied dashboard access to telegram user %s", user_id)
        return page(
            f"<main class=login><h2>Not authorised</h2><p>Telegram "
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

    # Filters live in ONE row above everything they scope, and are plain links
    # so the whole page re-renders against the same slice — no per-card
    # controls, and no JavaScript.
    try:
        days = int(request.query_params.get("days", 14))
    except ValueError:
        days = 14
    days = days if days in (7, 14, 30) else 14
    raw_chat = request.query_params.get("chat", "")
    chat_id = int(raw_chat) if raw_chat.lstrip("-").isdigit() else None

    try:
        conn = queries.connect(settings.db_path)
    except Exception as exc:
        return page(
            f"<main><section><h2>Database unavailable</h2>"
            f"<div class=card><p>{e(exc)}</p><p class=dim>Expected at "
            f"<code>{e(settings.db_path)}</code>. The panel opens it read-only, "
            f"so it must already exist &mdash; start the bot once first.</p>"
            f"</div></section></main>", user_id,
        )
    try:
        ov = queries.overview(conn, chat_id)
        acc = queries.accuracy(conn, chat_id)
        daily = queries.daily_activity(conn, chat_id, days=days)
        chats = queries.per_chat(conn)
        events = queries.recent_events(conn, chat_id)
        offenders = queries.top_offenders(conn, chat_id)
        hp = queries.health(conn)
    finally:
        conn.close()

    def link(days_v=None, chat_v="keep"):
        params = {"days": days_v if days_v is not None else days}
        target = chat_id if chat_v == "keep" else chat_v
        if target is not None:
            params["chat"] = target
        return "/?" + "&".join(f"{k}={v}" for k, v in params.items())

    def chip(label, href, current):
        return (
            f'<a class="chip" href="{href}" '
            f'aria-current="{"true" if current else "false"}">{label}</a>'
        )

    ranges = "".join(chip(f"{d}d", link(days_v=d), d == days) for d in (7, 14, 30))
    chat_chips = chip("All groups", link(chat_v=None), chat_id is None) + "".join(
        chip(e(c["title"] or str(c["chat_id"])[-6:]), link(chat_v=c["chat_id"]),
             chat_id == c["chat_id"])
        for c in chats[:6]
    )
    filters = (
        f'<div class="filters">'
        f'<div class="fgroup"><span class="flabel">Period</span>{ranges}</div>'
        f'<div class="fgroup"><span class="flabel">Group</span>{chat_chips}</div>'
        f'</div>'
    )

    # --- hero + tiles ------------------------------------------------------
    selected = next((c for c in chats if c["chat_id"] == chat_id), None)
    group_name = (selected or {}).get("title") or (
        str(chat_id) if chat_id is not None else ""
    )
    period_actions = sum(d["REVIEW"] + d["DELETE"] + d["BAN"] for d in daily)
    per_day = period_actions / days if days else 0
    hero = (
        f'<div class="hero"><span class="v">{period_actions}</span>'
        f'<span class="k">moderation actions in the last {days} days'
        f'{" in " + e(group_name) if chat_id is not None else " across all groups"}<br>'
        f'<span class="dim">{per_day:.1f} per day &middot; last activity '
        f'{_ago(hp["last_event"])}</span></span></div>'
    )
    tiles = "".join(
        f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div></div>'
        for k, v in (
            (f"group{'' if len(chats) == 1 else 's'} watched", len(chats)),
            ("known members", ov["users"]),
            ("messages seen", ov["messages_seen"]),
            ("active strikes", ov["active_strikes"]),
            ("banned", ov["banned"]),
            ("whitelisted", ov["whitelisted"]),
        )
    )

    # --- chart + its table view (never color-only) -------------------------
    day_rows = "".join(
        f'<tr><td class="num">{d["day"]}</td><td class="num">{d["BAN"]}</td>'
        f'<td class="num">{d["DELETE"]}</td><td class="num">{d["REVIEW"]}</td></tr>'
        for d in reversed(daily)
    )
    table_view = (
        f'<details><summary>&#9656; table view</summary>'
        f'<div class="wrap" style="margin-top:10px"><table><thead><tr>'
        f'<th>day</th><th>ban</th><th>delete</th><th>review</th></tr></thead>'
        f'<tbody>{day_rows}</tbody></table></div></details>'
    )
    chart = (
        f'<div class="card">{render.legend()}{render.bar_chart(daily)}</div>'
        f'{table_view}'
    )

    # --- accuracy ----------------------------------------------------------
    rate = acc["overturn_rate"]
    rate_text = f"{rate * 100:.0f}%" if rate is not None else "&mdash;"
    acc_tiles = "".join(
        f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div></div>'
        for k, v in (
            ("decisions made", acc["bot_actions"]),
            ("reviewed by a human", acc["reviewed"]),
            ("overturned", acc["overturned"]),
            ("overturn rate", rate_text),
        )
    )
    if acc["reviewed"]:
        caveat = (
            f"<strong>An upper bound, not a measurement.</strong> Only "
            f"{acc['reviewed']} of {acc['bot_actions']} decisions were reviewed, "
            f"and nobody taps a button on the obviously correct ones &mdash; so "
            f"the sample is biased toward mistakes. Directional evidence about "
            f"your thresholds, not a false-positive rate."
        )
    else:
        caveat = (
            "<strong>No human has reviewed a decision yet.</strong> Tap Ignore "
            "or Ban on the alerts in Telegram &mdash; Ignore records the bot as "
            "wrong, Ban records it as right. Until then there is no evidence "
            "either way about whether these thresholds are safe to enforce with."
        )

    # --- tables ------------------------------------------------------------
    event_rows = "".join(
        f'<tr><td class="dim num">{_when(ev["ts"])}</td>'
        f'<td><span class="tag" style="background:{_tint(ev["action"])};'
        f'color:{_ink(ev["action"])}">{e(ev["action"])}</span></td>'
        f'<td>{"@" + e(ev["username"]) if ev["username"] else e(ev["user_id"])}</td>'
        f'<td class="mono">{str(ev["chat_id"])[-6:]}</td>'
        f'<td class="msg">{e(ev["reason"])}</td>'
        f'<td class="msg dim">{e(ev["text"])}</td></tr>'
        for ev in events
    )
    offender_rows = "".join(
        f'<tr><td>{"@" + e(o["username"]) if o["username"] else e(o["user_id"])}</td>'
        f'<td class="mono">{str(o["chat_id"])[-6:]}</td>'
        f'<td class="num">{o["lifetime"]}</td>'
        f'<td class="num dim">{o["messages_seen"]}</td>'
        f'<td class="dim">{e(o["status"])}</td></tr>'
        for o in offenders
    )

    def block(title, sub, head, rows, empty):
        body = (
            f'<div class="wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            if rows else f'<div class="wrap"><div class="empty">{empty}</div></div>'
        )
        return (
            f'<section><div class="head"><h2>{title}</h2>'
            f'<span class="sub">{sub}</span></div>{body}</section>'
        )

    scope = "" if chat_id is None else f" &middot; {e(group_name)}"
    return page(
        "<main>"
        + filters
        + f'<section>{hero}<div class="tiles" style="margin-top:12px">{tiles}'
          f'</div></section>'
        + f'<section><div class="head"><h2>Activity</h2>'
          f'<span class="sub">last {days} days{scope}</span></div>'
          f'{chart}</section>'
        + f'<section><div class="head"><h2>Is it getting it right?</h2></div>'
          f'<div class="tiles">{acc_tiles}</div>'
          f'<div class="note">{caveat}</div></section>'
        + f'<section><div class="head"><h2>Groups</h2>'
          f'<span class="sub">{len(chats)} watched &middot; all time &middot; '
          f'click one to filter</span></div>'
          f'{render.group_cards(chats, lambda cid: link(chat_v=cid), e, _ago)}'
          f'</section>'
        + block("Most strikes",
                "lifetime, including expired"
                + ("" if chat_id is None else f" &middot; {e(group_name)}"),
                "<th>member</th><th>chat</th><th>strikes</th><th>messages</th>"
                "<th>status</th>",
                offender_rows, "Nobody has a strike.")
        + block("Recent decisions", f"latest {len(events)}",
                "<th>when (utc)</th><th>action</th><th>member</th><th>chat</th>"
                "<th>why</th><th>message</th>",
                event_rows, "Nothing recorded yet.")
        + "</main>",
        user_id,
    )


def _tint(action: str) -> str:
    """Muted background for an action pill — a wash of the series hue, so the
    tag reads as the same entity as its bar without competing with it."""
    return {
        "BAN": "#3a1f2a", "DELETE": "#2d2510", "REVIEW": "#152435",
    }.get(action, "#241f38")


def _ink(action: str) -> str:
    return {
        "BAN": render.SERIES["BAN"],
        "DELETE": render.SERIES["DELETE"],
        "REVIEW": render.SERIES["REVIEW"],
    }.get(action, render.ADMIN_TINT)


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
<h2>Maxfiylik siyosati</h2>
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
</main>"""
    return page(body, _current_user(request))


@app.get("/healthz")
async def healthz():
    """Unauthenticated on purpose: it reveals nothing and lets an uptime
    monitor check the panel itself."""
    return {"ok": True}
