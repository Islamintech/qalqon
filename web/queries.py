"""Read-only views over the moderation database.

Opened with SQLite's `mode=ro` URI so the web process CANNOT write, no matter
what a bug or a compromise there does. Moderation state is the bot's alone; the
panel only looks. That is also why this does not import Store — reusing the
writable class would make a stray write one typo away.

Concurrency: SQLite readers do not block the bot's writes as long as WAL is on,
which the bot enables. A reader may briefly see a slightly stale page; for a
dashboard that is fine.
"""
import sqlite3
import time
from datetime import datetime, timezone

DAY = 86400.0


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _scope(chat_id: int | None) -> tuple[str, tuple]:
    if chat_id is None:
        return "WHERE 1=1", ()
    return "WHERE chat_id = ?", (chat_id,)


def overview(conn, chat_id: int | None = None) -> dict:
    where, args = _scope(chat_id)
    one = lambda sql, a=(): conn.execute(sql, a).fetchone()[0]
    return {
        "users": one(f"SELECT COUNT(*) FROM users {where}", args),
        "whitelisted": one(
            f"SELECT COUNT(*) FROM users {where} AND status='whitelisted'", args
        ),
        "banned": one(f"SELECT COUNT(*) FROM users {where} AND status='banned'", args),
        "active_strikes": one(f"SELECT COUNT(*) FROM strikes {where}", args),
        "events": one(f"SELECT COUNT(*) FROM events {where}", args),
        "messages_seen": one(
            f"SELECT COALESCE(SUM(messages_seen),0) FROM users {where}", args
        ),
    }


def daily_activity(conn, chat_id: int | None = None, days: int = 14) -> list[dict]:
    """One row per day, oldest first. Days with nothing are included as zeroes —
    a gap in a chart reads as missing data, not as a quiet day."""
    where, args = _scope(chat_id)
    since = time.time() - days * DAY
    rows = conn.execute(
        f"SELECT ts, action FROM events {where} AND ts >= ? "
        f"AND action IN ('REVIEW','DELETE','BAN')",
        (*args, since),
    ).fetchall()

    buckets: dict[str, dict[str, int]] = {}
    for i in range(days):
        day = datetime.fromtimestamp(
            time.time() - (days - 1 - i) * DAY, tz=timezone.utc
        ).strftime("%Y-%m-%d")
        buckets[day] = {"REVIEW": 0, "DELETE": 0, "BAN": 0}
    for r in rows:
        day = datetime.fromtimestamp(r["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        if day in buckets:
            buckets[day][r["action"]] = buckets[day].get(r["action"], 0) + 1
    return [{"day": d, **counts} for d, counts in buckets.items()]


def accuracy(conn, chat_id: int | None = None) -> dict:
    """How often a human overturned the bot.

    IMPORTANT: reviewed cases are a biased sample — nobody taps a button on the
    obviously-correct ones — so this is an UPPER BOUND on the false-positive
    rate, not a measurement of it. The template must say so; a number presented
    without that caveat would be trusted more than it deserves.
    """
    where, args = _scope(chat_id)
    row = conn.execute(
        f"SELECT SUM(risk='OVERTURNED') o, SUM(risk='CONFIRMED') c "
        f"FROM events {where} AND action LIKE 'ADMIN_%'",
        args,
    ).fetchone()
    overturned, confirmed = row["o"] or 0, row["c"] or 0
    reviewed = overturned + confirmed
    acted = conn.execute(
        f"SELECT COUNT(*) FROM events {where} AND action IN ('REVIEW','DELETE','BAN')",
        args,
    ).fetchone()[0]
    return {
        "bot_actions": acted,
        "reviewed": reviewed,
        "overturned": overturned,
        "confirmed": confirmed,
        "overturn_rate": (overturned / reviewed) if reviewed else None,
        "unreviewed": max(acted - reviewed, 0),
    }


def per_chat(conn) -> list[dict]:
    """One row per group the bot has ever seen, with everything the overview
    needs: the NAME (not just the id), how much it has moderated, and how many
    members are on record.

    Built from the chats table so a quiet group still appears — a group with
    zero incidents is a fact worth showing, and joining off events alone would
    hide exactly the groups that are behaving.
    """
    rows = conn.execute(
        """
        SELECT
          c.chat_id,
          c.title,
          c.last_seen,
          (SELECT COUNT(*)                FROM users u  WHERE u.chat_id = c.chat_id) AS members,
          (SELECT COALESCE(SUM(u.messages_seen),0)
                                          FROM users u  WHERE u.chat_id = c.chat_id) AS messages,
          (SELECT COUNT(*)                FROM users u  WHERE u.chat_id = c.chat_id
                                            AND u.status = 'banned')                 AS banned_now,
          (SELECT COUNT(*)                FROM strikes s WHERE s.chat_id = c.chat_id) AS strikes,
          (SELECT COUNT(*) FROM events e WHERE e.chat_id = c.chat_id AND e.action='BAN')    AS bans,
          (SELECT COUNT(*) FROM events e WHERE e.chat_id = c.chat_id AND e.action='DELETE') AS deletes,
          (SELECT COUNT(*) FROM events e WHERE e.chat_id = c.chat_id AND e.action='REVIEW') AS reviews,
          (SELECT MAX(ts)  FROM events e WHERE e.chat_id = c.chat_id)                       AS last_action
        FROM chats c
        """
    ).fetchall()
    out = [dict(r) for r in rows]

    # A chat that has events but was never registered (pre-v3 data) must not
    # vanish from the list just because we never learned its name.
    for r in conn.execute(
        "SELECT DISTINCT chat_id FROM events WHERE chat_id NOT IN "
        "(SELECT chat_id FROM chats)"
    ).fetchall():
        out.append({
            "chat_id": r["chat_id"], "title": "", "last_seen": None,
            "members": 0, "messages": 0, "banned_now": 0, "strikes": 0,
            "bans": 0, "deletes": 0, "reviews": 0, "last_action": None,
        })
    out.sort(key=lambda c: (c["bans"] + c["deletes"] + c["reviews"]), reverse=True)
    return out


def chat_title(conn, chat_id: int) -> str:
    row = conn.execute(
        "SELECT title FROM chats WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    return (row["title"] if row else "") or ""


def recent_events(conn, chat_id: int | None = None, limit: int = 60) -> list[dict]:
    where, args = _scope(chat_id)
    rows = conn.execute(
        f"SELECT e.ts, e.chat_id, e.user_id, e.action, e.risk, e.reason, e.text, "
        f"  COALESCE(u.username,'') AS username "
        f"FROM events e LEFT JOIN users u "
        f"  ON u.chat_id = e.chat_id AND u.user_id = e.user_id "
        f"{where.replace('chat_id', 'e.chat_id')} ORDER BY e.ts DESC LIMIT ?",
        (*args, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def top_offenders(conn, chat_id: int | None = None, limit: int = 10) -> list[dict]:
    scope = "AND chat_id = ?" if chat_id is not None else ""
    args = (chat_id, limit) if chat_id is not None else (limit,)
    rows = conn.execute(
        "SELECT chat_id, user_id, username, strikes AS lifetime, status, "
        "messages_seen FROM users WHERE strikes > 0 "
        f"{scope} ORDER BY strikes DESC LIMIT ?",
        args,
    ).fetchall()
    return [dict(r) for r in rows]


def health(conn) -> dict:
    """Last time the bot wrote anything. Not a substitute for the heartbeat —
    a quiet chat also produces no writes — but a long gap alongside busy groups
    is worth seeing."""
    row = conn.execute("SELECT MAX(ts) AS last FROM events").fetchone()
    last = row["last"]
    return {
        "last_event": last,
        "seconds_since": (time.time() - last) if last else None,
    }


# --- usage / cost ----------------------------------------------------------
def usage_summary(conn, chat_id: int | None = None, days: int = 14) -> dict:
    """What the analysis actually cost, and how close it runs to the ceiling.

    `analysed` counts every attempt that reached the model layer, including
    cache hits and failures. Without that denominator the cache looks free and
    the failures disappear.
    """
    where, args = _scope(chat_id)
    since = time.time() - days * DAY
    row = conn.execute(
        f"SELECT COUNT(*) attempts, "
        f"  SUM(cached) cached, SUM(ok=0) failed, "
        f"  SUM(prompt_tokens) pin, SUM(completion_tokens) pout, "
        f"  SUM(reasoning_tokens) reasoning, "
        f"  AVG(NULLIF(latency_ms,0)) avg_ms, MAX(latency_ms) max_ms, "
        f"  AVG(NULLIF(queue_ms,0)) avg_queue "
        f"FROM usage {where} AND ts >= ?",
        (*args, since),
    ).fetchone()
    attempts = row["attempts"] or 0
    cached = row["cached"] or 0
    billed = attempts - cached - (row["failed"] or 0)
    # Messages the bot saw but never sent to the model at all — short chatter,
    # trusted members, admins, whitelisted. The cheapest call is the one never
    # made, so this is the number worth watching.
    seen = conn.execute(
        f"SELECT COALESCE(SUM(messages_seen),0) FROM users {where}", args
    ).fetchone()[0]
    return {
        "attempts": attempts,
        "billed": max(billed, 0),
        "cached": cached,
        "failed": row["failed"] or 0,
        "prompt_tokens": row["pin"] or 0,
        "completion_tokens": row["pout"] or 0,
        "reasoning_tokens": row["reasoning"] or 0,
        "total_tokens": (row["pin"] or 0) + (row["pout"] or 0),
        "avg_ms": int(row["avg_ms"] or 0),
        "max_ms": int(row["max_ms"] or 0),
        "avg_queue_ms": int(row["avg_queue"] or 0),
        "messages_seen": seen,
        "model": _busiest_model(conn, since),
    }


def _busiest_model(conn, since: float) -> str:
    row = conn.execute(
        "SELECT model, COUNT(*) c FROM usage WHERE ts >= ? AND model != '' "
        "GROUP BY model ORDER BY c DESC LIMIT 1",
        (since,),
    ).fetchone()
    return row["model"] if row else ""


def usage_daily(conn, chat_id: int | None = None, days: int = 14) -> list[dict]:
    where, args = _scope(chat_id)
    since = time.time() - days * DAY
    rows = conn.execute(
        f"SELECT ts, prompt_tokens, completion_tokens, cached FROM usage "
        f"{where} AND ts >= ?",
        (*args, since),
    ).fetchall()
    buckets = {}
    for i in range(days):
        day = datetime.fromtimestamp(
            time.time() - (days - 1 - i) * DAY, tz=timezone.utc
        ).strftime("%Y-%m-%d")
        buckets[day] = {"tokens": 0, "calls": 0, "cached": 0}
    for r in rows:
        day = datetime.fromtimestamp(r["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        if day not in buckets:
            continue
        buckets[day]["tokens"] += (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
        buckets[day]["calls"] += 1
        buckets[day]["cached"] += 1 if r["cached"] else 0
    return [{"day": d, **v} for d, v in buckets.items()]


def busiest_minute(conn, days: int = 14) -> dict:
    """The peak token-per-minute burst.

    This is the number that matters operationally: the free tier caps tokens
    per MINUTE, not per day, so a quiet week with one busy minute still gets
    rate-limited — and a rate-limited moderator is a blind one.
    """
    since = time.time() - days * DAY
    rows = conn.execute(
        "SELECT CAST(ts/60 AS INTEGER) m, "
        "SUM(prompt_tokens + completion_tokens) t, COUNT(*) c "
        "FROM usage WHERE ts >= ? AND cached = 0 GROUP BY m ORDER BY t DESC LIMIT 1",
        (since,),
    ).fetchone()
    if not rows or not rows["t"]:
        return {"tokens": 0, "calls": 0, "at": None}
    return {"tokens": rows["t"], "calls": rows["c"], "at": rows["m"] * 60}


def usage_by_chat(conn, days: int = 14) -> list[dict]:
    since = time.time() - days * DAY
    rows = conn.execute(
        "SELECT chat_id, COUNT(*) attempts, SUM(cached) cached, "
        "  SUM(prompt_tokens + completion_tokens) tokens "
        "FROM usage WHERE ts >= ? GROUP BY chat_id ORDER BY tokens DESC",
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]
