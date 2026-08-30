"""The dashboard's pages.

Four of them rather than one long scroll, because the questions are different:
"is it working", "which group has trouble", "who is a problem", "what happened".
Stacking all four made every answer require scrolling past the other three.

Everything here is presentation. Data comes from web.queries (read-only), and
nothing in this module can write.
"""
import html
import time
from datetime import datetime, timezone

from web import render


def e(value) -> str:
    """Escape everything. Usernames, reasons and message text are all
    attacker-controlled — a member choosing a name with a <script> tag in it
    must not run code in an admin's browser."""
    return html.escape(str(value if value is not None else ""), quote=True)


def ago(ts: float | None) -> str:
    if not ts:
        return "never"
    s = int(max(time.time() - ts, 0))
    if s < 90:
        return "just now"
    if s < 5400:
        return f"{s // 60} min ago"
    if s < 172800:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


def when(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b, %H:%M")


def who(username: str, user_id: int) -> str:
    return f"@{e(username)}" if username else f"Member {e(user_id)}"


def group_name(chats, chat_id) -> str:
    for c in chats:
        if c["chat_id"] == chat_id:
            return c["title"] or f"Group {str(c['chat_id'])[-6:]}"
    return f"Group {str(chat_id)[-6:]}"


def head(title: str, subtitle: str = "", extra: str = "") -> str:
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    return (
        f'<div class="phead"><div><h1>{title}</h1>{sub}</div>'
        f'<div class="grow"></div>{extra}</div>'
    )


def tiles(pairs) -> str:
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div></div>'
        for k, v in pairs
    ) + "</div>"


def act_chip(action: str) -> str:
    label, icon = render.LABEL.get(action, (action, "•"))
    return f'<span class="act {e(action)}">{icon} {label}</span>'


# --- pages -----------------------------------------------------------------
def overview(data) -> str:
    """Answers one question: is it working, and is it getting it right?"""
    acc, chats, ov, daily = data["acc"], data["chats"], data["ov"], data["daily"]
    period = sum(d["REVIEW"] + d["DELETE"] + d["BAN"] for d in daily)

    if not chats:
        return head("Overview") + render.empty(
            "🛡️", "Qalqon is running, but not watching anything yet",
            "Add the bot to a group and make it an administrator with "
            "permission to delete messages and ban users. It starts working "
            "there immediately — nothing to configure here.",
            "1. Add <b>@QalqonSafeBot</b> to your group<br>"
            "2. Group settings → Administrators → add it<br>"
            "3. Allow <b>Delete messages</b> and <b>Ban users</b>",
        )

    rate = acc["overturn_rate"]
    if acc["reviewed"]:
        verdict = (
            f'<div class="note"><b>Read this as an upper bound.</b> Only '
            f'{acc["reviewed"]} of {acc["bot_actions"]} decisions were reviewed '
            f'by a person, and nobody taps a button on the obviously correct '
            f'ones — so the sample leans toward mistakes.</div>'
        )
        right = f"{(1 - rate) * 100:.0f}%"
    else:
        verdict = (
            '<div class="note"><b>Nobody has checked its work yet.</b> When an '
            'alert arrives in Telegram, tap <b>👌 Ignore</b> if Qalqon was '
            'wrong or <b>🚫 Ban</b> if it was right. Until then there is no '
            'evidence either way about whether it is safe to let it act.</div>'
        )
        right = "—"

    return (
        head("Overview", f"{len(chats)} group{'' if len(chats) == 1 else 's'} watched")
        + f'<div class="card hero"><div><div class="v">{period}</div></div>'
        f'<div class="k"><b>actions in the last {data["days"]} days</b><br>'
        f'{ov["messages_seen"]} messages read · last activity '
        f'{ago(data["health"]["last_event"])}</div></div>'
        + tiles([
            ("members known", ov["users"]),
            ("currently banned", ov["banned"]),
            ("trusted", ov["whitelisted"]),
            ("active strikes", ov["active_strikes"]),
        ])
        + head("Is it getting it right?")
        + tiles([
            ("decisions made", acc["bot_actions"]),
            ("checked by you", acc["reviewed"]),
            ("you disagreed", acc["overturned"]),
            ("agreed with", right),
        ])
        + verdict
    )


def groups(data) -> str:
    chats = data["chats"]
    if not chats:
        return head("Groups") + render.empty(
            "◍", "No groups yet",
            "Qalqon watches a group as soon as it is added to it as an "
            "administrator.",
        )

    cards = []
    for c in chats:
        quiet = (c["bans"] + c["deletes"] + c["reviews"]) == 0
        name = e(c["title"]) if c["title"] else "Unnamed group"
        sub = (
            f'{c["members"]} members · {c["messages"]} messages read'
            if c["title"] else
            "name appears after its next message"
        )
        cards.append(
            f'<a class="gcard" href="/activity?chat={c["chat_id"]}">'
            f'<div class="gname">{name}</div><div class="gsub">{sub}</div>'
            f'<div class="gnums">'
            f'<div class="gnum"><b style="color:var(--delete)">{c["deletes"]}</b>'
            f'<span>deleted</span></div>'
            f'<div class="gnum"><b style="color:var(--ban)">{c["bans"]}</b>'
            f'<span>removed</span></div>'
            f'<div class="gnum"><b style="color:var(--review)">{c["reviews"]}</b>'
            f'<span>to review</span></div></div>'
            f'<div class="gfoot">'
            f'{"Nothing has happened here yet" if quiet else "Last action " + ago(c["last_action"])}'
            f'</div></a>'
        )
    return (
        head("Groups", "Tap a group to see what happened there")
        + f'<div class="gcards">{"".join(cards)}</div>'
    )


def members(data) -> str:
    offenders, chats = data["offenders"], data["chats"]
    if not offenders:
        return head("Members") + render.empty(
            "◎", "Nobody has a strike",
            "Members appear here once Qalqon has acted on something they "
            "posted. An empty list means the groups are clean — or that "
            "nothing has been posted yet.",
        )
    rows = "".join(
        f"<tr><td>{who(o['username'], o['user_id'])}</td>"
        f"<td class=dim>{e(group_name(chats, o['chat_id']))}</td>"
        f"<td class=num>{o['lifetime']}</td>"
        f"<td class=num dim>{o['messages_seen']}</td>"
        f"<td>{_status_chip(o['status'])}</td></tr>"
        for o in offenders
    )
    return (
        head("Members", "Anyone Qalqon has acted on, most strikes first")
        + f'<div class="card wrap"><table><thead><tr><th>member</th>'
        f"<th>group</th><th>strikes</th><th>messages</th><th>status</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
        + '<div class="note">Strikes expire, so a member who behaves stops '
        "being escalated. “Trusted” members are never acted on "
        "automatically.</div>"
    )


def _status_chip(status: str) -> str:
    text = {
        "banned": "Removed", "whitelisted": "Trusted", "normal": "Normal",
    }.get(status, status)
    cls = {"banned": "BAN", "whitelisted": "ADMIN_WHITELIST"}.get(status, "REVIEW")
    if status == "normal":
        return '<span class="dim">Normal</span>'
    return f'<span class="act {cls}">{text}</span>'


def activity(data) -> str:
    events, chats, daily = data["events"], data["chats"], data["daily"]
    chat_id, days = data["chat_id"], data["days"]

    scope = "all groups" if chat_id is None else group_name(chats, chat_id)
    filters = '<div class="filters">' + "".join(
        f'<a class="chip" href="{data["link"](days_v=d)}" '
        f'aria-current="{"true" if d == days else "false"}">{d} days</a>'
        for d in (7, 14, 30)
    ) + "".join(
        f'<a class="chip" href="{data["link"](chat_v=cid)}" '
        f'aria-current="{"true" if chat_id == cid else "false"}">{e(label)}</a>'
        for cid, label in [(None, "All groups")]
        + [(c["chat_id"], c["title"] or str(c["chat_id"])[-6:]) for c in chats[:5]]
    ) + "</div>"

    if not events:
        return (
            head("Activity", f"{scope} · last {days} days")
            + filters
            + render.empty(
                "◔", "Nothing has happened",
                "Qalqon has not needed to act in this period. That is the "
                "outcome you want — it means nothing suspicious was posted.",
            )
        )

    day_rows = "".join(
        f'<tr><td class=num>{d["day"]}</td><td class=num>{d["BAN"]}</td>'
        f'<td class=num>{d["DELETE"]}</td><td class=num>{d["REVIEW"]}</td></tr>'
        for d in reversed(daily)
    )
    chart = (
        f'<div class="card pad">{render.legend()}{render.bar_chart(daily)}'
        f'<details><summary>▸ Show as a table</summary>'
        f'<div class="wrap" style="margin-top:12px"><table><thead><tr>'
        f"<th>day</th><th>removed</th><th>deleted</th><th>to review</th></tr>"
        f"</thead><tbody>{day_rows}</tbody></table></div></details></div>"
    )

    feed = "".join(_feed_item(ev, chats) for ev in events)
    return (
        head("Activity", f"{scope} · last {days} days")
        + filters + chart
        + '<div style="height:20px"></div>'
        + f'<div class="card feed">{feed}</div>'
    )


def _feed_item(ev, chats) -> str:
    """One line of the activity feed.

    The message itself is the thing an operator needs to judge, so it is shown
    plainly. The machine reasoning ("content=RED_FLAG(llm); profile=CLEAN")
    goes behind a disclosure — useful when you want it, noise when you do not.
    """
    said = (
        f'<div class="said">{e(ev["text"])}</div>' if ev["text"] else ""
    )
    return (
        f'<div class="item"><div style="flex:1;min-width:0">'
        f'<div class="who">{who(ev["username"], ev["user_id"])} '
        f'{act_chip(ev["action"])}</div>'
        f'<div class="meta">in {e(group_name(chats, ev["chat_id"]))}</div>'
        f'{said}'
        f'<details><summary>Why?</summary>'
        f'<div class="meta" style="margin-top:6px">{e(ev["reason"])}</div>'
        f'</details></div>'
        f'<div class="when">{when(ev["ts"])}</div></div>'
    )


def usage(data) -> str:
    """What the analysis costs, and how close it runs to the rate limit.

    Cost is the least interesting number here — moderating a hundred thousand
    messages runs to single-digit dollars. The figures that decide whether this
    keeps working are the peak tokens-per-minute against the account's ceiling,
    and how many messages never reached the model at all.
    """
    u, prices = data["usage"], data["prices"]
    peak, days = data["peak"], data["days"]
    model = u["model"] or data["model"]

    if not u["attempts"]:
        return pages_head_usage() + render.empty(
            "◔", "No analysis recorded yet",
            "Every message Qalqon sends to the language model is logged here "
            "with its token count and latency. Nothing has been analysed in "
            "this period.",
        )

    from web import pricing

    total = pricing.cost(
        model, u["prompt_tokens"], u["completion_tokens"], prices
    )
    per_k = pricing.per_thousand(model, u, prices)

    # Groq exposes no billing endpoint, so whether this key is charged cannot
    # be detected. Printing a dollar figure for a free-tier key would be
    # inventing a bill, so the wording changes instead of the number.
    if data["billed"]:
        cost_label, free_note = "cost", ""
    else:
        cost_label = "list price equivalent"
        free_note = (
            '<div class="note"><b>You are marked as being on the free tier, so '
            "this is not a bill.</b> The figures are what this usage would cost "
            "at list price — useful for projecting a paid plan, but nothing is "
            "charged. Check your plan at console.groq.com and set "
            "<code>GROQ_PLAN=paid</code> if that is wrong.</div>"
        )

    # The ceiling that actually bites: tokens per minute, not per day.
    limit = data["token_limit"]
    pct = (peak["tokens"] / limit * 100) if limit and peak["tokens"] else 0
    if pct >= 90:
        headroom = ('<div class="note"><b>At the limit.</b> A busy minute has '
                    f'already reached {pct:.0f}% of your {limit:,} tokens/minute '
                    'allowance. Beyond it Qalqon is rate-limited and falls back '
                    'to keyword checks only — it keeps running, but stops '
                    'seeing subtle scams. Raising the tier or trimming the '
                    'prompt would both help.</div>')
    elif pct >= 50:
        headroom = ('<div class="note"><b>Worth watching.</b> The busiest minute '
                    f'used {pct:.0f}% of your {limit:,} tokens/minute allowance. '
                    'A raid or a second busy group could exceed it.</div>')
    else:
        headroom = ""

    skipped = max(u["messages_seen"] - u["attempts"], 0)
    skip_pct = (skipped / u["messages_seen"] * 100) if u["messages_seen"] else 0

    avg_prompt = (u["prompt_tokens"] // u["billed"]) if u["billed"] else 0
    prompt_share = (
        u["prompt_tokens"] / u["total_tokens"] * 100 if u["total_tokens"] else 0
    )

    chart = ""
    if any(d["tokens"] for d in data["usage_daily"]):
        chart = (
            f'<div class="card pad" style="margin-bottom:26px">'
            f'{render.tokens_chart(data["usage_daily"])}</div>'
        )

    rows = "".join(
        f'<tr><td>{e(group_name(data["chats"], c["chat_id"]))}</td>'
        f'<td class=num>{c["attempts"]}</td>'
        f'<td class=num dim>{c["cached"] or 0}</td>'
        f'<td class=num>{c["tokens"]:,}</td>'
        f'<td class=num>{pricing.money(pricing.cost(model, c["tokens"], 0, prices))}'
        f"</td></tr>"
        for c in data["usage_by_chat"]
    )
    by_chat = (
        f'<div class="card wrap"><table><thead><tr><th>group</th>'
        f"<th>analysed</th><th>from cache</th><th>tokens</th><th>cost</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
        if rows else ""
    )

    return (
        pages_head_usage(f"last {days} days · {e(model)}")
        + tiles([
            ("messages analysed", f'{u["attempts"]:,}'),
            ("tokens used", f'{u["total_tokens"]:,}'),
            (cost_label, pricing.money(total)),
            ("per 1,000 messages", pricing.money(per_k)),
        ])
        + free_note
        + chart
        + head("Throughput", "the limit is per minute, not per day")
        + tiles([
            ("busiest minute", f'{peak["tokens"]:,} tok'),
            ("of the limit", f"{pct:.0f}%" if limit else "—"),
            ("average reply", f'{u["avg_ms"]:,} ms'),
            ("slowest reply", f'{u["max_ms"]:,} ms'),
        ])
        + headroom
        + head("What was avoided", "the cheapest call is the one never made")
        + tiles([
            ("never sent to the model", f"{skipped:,}"),
            ("of all messages", f"{skip_pct:.0f}%"),
            ("answered from cache", f'{u["cached"]:,}'),
            ("failed calls", f'{u["failed"]:,}'),
        ])
        + f'<div class="note"><b>{avg_prompt:,} tokens go in for every reply, '
          f"and {prompt_share:.0f}% of all tokens are the prompt rather than the "
          f"answer.</b> The instructions are re-sent with every single message, "
          f"so shortening them is the one change that reduces both cost and "
          f"rate-limit pressure — for every group at once.</div>"
        + (head("By group", f"last {days} days") + by_chat if by_chat else "")
    )


def pages_head_usage(sub: str = "") -> str:
    return head("Usage", sub or "Token spend, speed, and what was avoided")
