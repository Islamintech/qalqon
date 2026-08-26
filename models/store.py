"""Per-user memory. Without this the bot judges every message in isolation and
a serial scammer looks exactly like a first-time poster.

SQLite via the stdlib, moved off the event loop with asyncio.to_thread — no new
dependency, and a moderation bot's write rate is nowhere near needing more.

Per (chat, user) we remember:
  - messages_seen    : how established the member is       -> trust
  - strikes          : confirmed-bad events, WITH a timestamp so they can age
                       out                                 -> escalation
  - lifetime_strikes : the same events, never decayed      -> admin context
  - status           : normal | whitelisted | banned       -> admin overrides

STRIKE DECAY
Strikes expire after `decay_days`. One bad week two years ago should not still
be pushing someone toward a ban today, and without decay the strike count only
ever ratchets upward — every long-lived member eventually accumulates enough
noise to get auto-banned by a single borderline message. The lifetime total is
kept separately so an admin running /status can still see the full history.
Set decay_days to 0 to disable ageing entirely.
"""
import asyncio
import sqlite3
import time
from dataclasses import dataclass

STATUS_NORMAL = "normal"
STATUS_WHITELISTED = "whitelisted"
STATUS_BANNED = "banned"

DAY = 86400.0
SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    username      TEXT    NOT NULL DEFAULT '',
    messages_seen INTEGER NOT NULL DEFAULT 0,
    strikes       INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'normal',
    first_seen    REAL    NOT NULL DEFAULT 0,
    last_seen     REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS strikes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ts      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS strikes_user ON strikes (chat_id, user_id, ts);
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    ts        REAL    NOT NULL,
    action    TEXT    NOT NULL,
    risk      TEXT    NOT NULL,
    reason    TEXT    NOT NULL,
    text      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_user ON events (chat_id, user_id, ts DESC);
CREATE TABLE IF NOT EXISTS chats (
    chat_id    INTEGER PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    first_seen REAL NOT NULL DEFAULT 0,
    last_seen  REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class UserRecord:
    chat_id: int
    user_id: int
    username: str = ""
    messages_seen: int = 0
    strikes: int = 0            # ACTIVE strikes — what the policy escalates on
    lifetime_strikes: int = 0   # never decays; for admin context only
    status: str = STATUS_NORMAL
    first_seen: float = 0.0
    last_seen: float = 0.0
    oldest_active_strike: float | None = None

    @property
    def whitelisted(self) -> bool:
        return self.status == STATUS_WHITELISTED

    def trusted(self, min_messages: int) -> bool:
        """Trusted once they have posted enough with no ACTIVE strike — or when
        an admin whitelisted them outright. Decay is what lets someone earn
        their way back here; a permanent lifetime bar would make forgiveness
        impossible."""
        if self.whitelisted:
            return True
        return self.strikes == 0 and self.messages_seen >= min_messages

    def strikes_expire_at(self, decay_days: int) -> float | None:
        """When the oldest active strike drops off, or None if nothing will."""
        if not decay_days or self.oldest_active_strike is None:
            return None
        return self.oldest_active_strike + decay_days * DAY


class Store:
    def __init__(
        self, path: str = "qalqon.db", decay_days: int = 30,
        event_retention_days: int = 90,
    ) -> None:
        self._path = path
        self._decay_days = max(int(decay_days), 0)
        self._retention_days = max(int(event_retention_days), 0)
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None
        # Last title written per chat, so a rename is persisted but an
        # unchanged name is not rewritten on every single message.
        self._chat_titles: dict[int, str] = {}

    @property
    def decay_days(self) -> int:
        return self._decay_days

    def _cutoff(self, now: float | None = None) -> float:
        """Strikes at or after this timestamp still count. 0 disables decay."""
        if not self._decay_days:
            return 0.0
        return (now if now is not None else time.time()) - self._decay_days * DAY

    # --- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # WAL lets a reader (the web dashboard) run concurrently with the
            # bot's writes instead of the two blocking each other. It also
            # survives an unclean shutdown better, which matters under
            # Restart=always.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA)
            _migrate(conn)
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_open)

    async def stop(self) -> None:
        if self._conn is not None:
            conn, self._conn = self._conn, None
            await asyncio.to_thread(conn.close)

    async def _run(self, fn, *args):
        if self._conn is None:
            raise RuntimeError("Store.start() was never awaited")
        # One writer at a time: SQLite serializes anyway, and the lock keeps
        # read-modify-write pairs (bump strikes, then read back) atomic.
        async with self._lock:
            return await asyncio.to_thread(fn, self._conn, *args)

    # --- reads -----------------------------------------------------------
    def _active(self, conn, chat_id: int, user_id: int, cutoff: float) -> tuple[int, float | None]:
        row = conn.execute(
            "SELECT COUNT(*) n, MIN(ts) oldest FROM strikes "
            "WHERE chat_id=? AND user_id=? AND ts >= ?",
            (chat_id, user_id, cutoff),
        ).fetchone()
        return row["n"], row["oldest"]

    async def get(self, chat_id: int, user_id: int) -> UserRecord:
        cutoff = self._cutoff()

        def _get(conn, chat_id, user_id, cutoff):
            row = conn.execute(
                "SELECT * FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            active, oldest = self._active(conn, chat_id, user_id, cutoff)
            if row is None:
                return UserRecord(
                    chat_id=chat_id, user_id=user_id,
                    strikes=active, oldest_active_strike=oldest,
                )
            return UserRecord(
                chat_id=row["chat_id"],
                user_id=row["user_id"],
                username=row["username"],
                messages_seen=row["messages_seen"],
                strikes=active,
                lifetime_strikes=row["strikes"],
                status=row["status"],
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
                oldest_active_strike=oldest,
            )

        return await self._run(_get, chat_id, user_id, cutoff)

    async def recent_events(
        self, chat_id: int, user_id: int, limit: int = 5
    ) -> list[dict]:
        def _ev(conn, chat_id, user_id, limit):
            rows = conn.execute(
                "SELECT ts, action, risk, reason, text FROM events "
                "WHERE chat_id=? AND user_id=? ORDER BY ts DESC LIMIT ?",
                (chat_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

        return await self._run(_ev, chat_id, user_id, limit)

    async def stats(self, chat_id: int | None = None) -> dict:
        cutoff = self._cutoff()

        def _stats(conn, chat_id, cutoff):
            scope = "WHERE chat_id = ?" if chat_id is not None else "WHERE 1=1"
            args: tuple = (chat_id,) if chat_id is not None else ()
            one = lambda sql, a: conn.execute(sql, a).fetchone()[0]
            actions = {
                r["action"]: r["c"]
                for r in conn.execute(
                    f"SELECT action, COUNT(*) c FROM events {scope} GROUP BY action",
                    args,
                ).fetchall()
            }
            return {
                "users": one(f"SELECT COUNT(*) FROM users {scope}", args),
                # Counted from live strike rows so it reflects decay, not the
                # lifetime column which never goes down.
                "users_with_strikes": one(
                    f"SELECT COUNT(DISTINCT user_id) FROM strikes {scope} AND ts >= ?",
                    (*args, cutoff),
                ),
                "active_strikes": one(
                    f"SELECT COUNT(*) FROM strikes {scope} AND ts >= ?",
                    (*args, cutoff),
                ),
                "whitelisted": one(
                    f"SELECT COUNT(*) FROM users {scope} AND status = ?",
                    (*args, STATUS_WHITELISTED),
                ),
                "events": one(f"SELECT COUNT(*) FROM events {scope}", args),
                "actions": actions,
            }

        return await self._run(_stats, chat_id, cutoff)

    # --- writes ----------------------------------------------------------
    async def touch(self, chat_id: int, user_id: int, username: str = "") -> UserRecord:
        """Record that we saw a message from this user, and return the record as
        it was BEFORE this message (so a first post reads messages_seen=0)."""
        cutoff = self._cutoff()

        def _touch(conn, chat_id, user_id, username, cutoff):
            now = time.time()
            row = conn.execute(
                "SELECT * FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            active, oldest = self._active(conn, chat_id, user_id, cutoff)
            if row is None:
                rec = UserRecord(
                    chat_id=chat_id, user_id=user_id, username=username,
                    strikes=active, oldest_active_strike=oldest,
                    first_seen=now, last_seen=now,
                )
                conn.execute(
                    "INSERT INTO users (chat_id,user_id,username,messages_seen,"
                    "strikes,status,first_seen,last_seen) VALUES (?,?,?,1,0,?,?,?)",
                    (chat_id, user_id, username, STATUS_NORMAL, now, now),
                )
            else:
                rec = UserRecord(
                    chat_id=row["chat_id"],
                    user_id=row["user_id"],
                    username=row["username"],
                    messages_seen=row["messages_seen"],
                    strikes=active,
                    lifetime_strikes=row["strikes"],
                    status=row["status"],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    oldest_active_strike=oldest,
                )
                conn.execute(
                    "UPDATE users SET messages_seen=messages_seen+1, last_seen=?,"
                    " username=? WHERE chat_id=? AND user_id=?",
                    (now, username or rec.username, chat_id, user_id),
                )
            conn.commit()
            return rec

        return await self._run(_touch, chat_id, user_id, username, cutoff)

    async def remember_chat(self, chat_id: int, title: str) -> None:
        """Record a group's name so the dashboard can show something a human
        recognises instead of -1004492159049.

        Guarded in memory: the title only changes when someone renames the
        group, so writing it on every message would be a pointless write on the
        hot path.
        """
        if title and self._chat_titles.get(chat_id) == title:
            return
        self._chat_titles[chat_id] = title

        def _remember(conn, chat_id, title):
            now = time.time()
            conn.execute(
                "INSERT INTO chats (chat_id,title,first_seen,last_seen) "
                "VALUES (?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET "
                "  title = CASE WHEN excluded.title != '' THEN excluded.title "
                "               ELSE chats.title END, "
                "  last_seen = excluded.last_seen",
                (chat_id, title or "", now, now),
            )
            conn.commit()

        await self._run(_remember, chat_id, title)

    async def chats(self) -> list[dict]:
        def _chats(conn):
            return [dict(r) for r in conn.execute(
                "SELECT chat_id, title, first_seen, last_seen FROM chats "
                "ORDER BY last_seen DESC"
            ).fetchall()]

        return await self._run(_chats)

    async def add_strike(
        self, chat_id: int, user_id: int, n: int = 1, ts: float | None = None
    ) -> int:
        """Record n strikes and return the ACTIVE count afterwards.

        `ts` exists so tests can backdate a strike; production always passes now.
        """
        cutoff = self._cutoff(ts)

        def _add(conn, chat_id, user_id, n, ts, cutoff):
            when = time.time() if ts is None else ts
            conn.executemany(
                "INSERT INTO strikes (chat_id,user_id,ts) VALUES (?,?,?)",
                [(chat_id, user_id, when)] * max(n, 0),
            )
            conn.execute(
                "INSERT INTO users (chat_id,user_id,strikes,first_seen,last_seen) "
                "VALUES (?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET "
                "strikes = strikes + excluded.strikes, last_seen = excluded.last_seen",
                (chat_id, user_id, n, when, when),
            )
            # Expired rows can never count again, so drop them here rather than
            # letting the table grow forever. The lifetime column keeps the total.
            if cutoff:
                conn.execute("DELETE FROM strikes WHERE ts < ?", (cutoff,))
            conn.commit()
            return self._active(conn, chat_id, user_id, cutoff)[0]

        return await self._run(_add, chat_id, user_id, n, ts, cutoff)

    async def set_status(self, chat_id: int, user_id: int, status: str) -> None:
        def _set(conn, chat_id, user_id, status):
            now = time.time()
            conn.execute(
                "INSERT INTO users (chat_id,user_id,status,first_seen,last_seen) "
                "VALUES (?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET "
                "status = excluded.status, last_seen = excluded.last_seen",
                (chat_id, user_id, status, now, now),
            )
            if status == STATUS_WHITELISTED:
                # Whitelisting forgives the past, otherwise old strikes would
                # keep escalating a user an admin just vouched for.
                conn.execute(
                    "DELETE FROM strikes WHERE chat_id=? AND user_id=?",
                    (chat_id, user_id),
                )
            conn.commit()

        await self._run(_set, chat_id, user_id, status)

    async def clear_strikes(self, chat_id: int, user_id: int) -> None:
        """Forgive the active strikes. The lifetime total is deliberately left
        alone — an admin looking at /status should still see the history."""

        def _clear(conn, chat_id, user_id):
            conn.execute(
                "DELETE FROM strikes WHERE chat_id=? AND user_id=?", (chat_id, user_id)
            )
            conn.execute(
                "UPDATE users SET status=? WHERE chat_id=? AND user_id=? AND status=?",
                (STATUS_NORMAL, chat_id, user_id, STATUS_BANNED),
            )
            conn.commit()

        await self._run(_clear, chat_id, user_id)

    async def prune_events(self) -> int:
        """Delete moderation records older than the retention window.

        The events table holds up to 500 characters of real people's messages —
        necessary to judge whether a flag was a false positive, but it is other
        people's private conversation, and keeping it forever is a choice
        nobody made deliberately. The audit value of a record decays quickly;
        the privacy cost does not.

        Aggregate counts in the dashboard shrink with it. That is the honest
        trade: the alternative is a permanent archive of group chat.
        Set retention to 0 to keep everything.
        """
        if not self._retention_days:
            return 0
        cutoff = time.time() - self._retention_days * DAY

        def _prune(conn, cutoff):
            cur = conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            conn.commit()
            return cur.rowcount

        return await self._run(_prune, cutoff)

    @property
    def retention_days(self) -> int:
        return self._retention_days

    async def prune_strikes(self) -> int:
        """Drop expired strike rows. add_strike does this opportunistically, but
        a quiet chat would never trigger it — so the bot also runs it on start."""
        cutoff = self._cutoff()

        def _prune(conn, cutoff):
            if not cutoff:
                return 0
            cur = conn.execute("DELETE FROM strikes WHERE ts < ?", (cutoff,))
            conn.commit()
            return cur.rowcount

        return await self._run(_prune, cutoff)

    async def log_event(
        self, chat_id: int, user_id: int, action: str, risk: str,
        reason: str, text: str = "",
    ) -> None:
        def _log(conn, *args):
            conn.execute(
                "INSERT INTO events (chat_id,user_id,ts,action,risk,reason,text) "
                "VALUES (?,?,?,?,?,?,?)",
                args,
            )
            conn.commit()

        await self._run(
            _log, chat_id, user_id, time.time(), action, risk, reason, text[:500]
        )


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to SCHEMA_VERSION.

    v1 -> v2: strikes were a bare counter with no timestamps. Backfill one row
    per counted strike, dated to the user's last_seen — the closest thing we
    have to when they offended. Erring toward last_seen (recent) rather than
    first_seen keeps existing offenders under watch instead of silently
    forgiving everyone the moment this ships.

    v2 -> v3: group titles were never stored, so the dashboard could only show
    numeric ids. Every chat we already know about is registered with an empty
    title; the real name fills in on that group's next message.
    """
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    version = int(row["value"]) if row is not None else 0
    if version >= SCHEMA_VERSION:
        return

    if version < 2:
        # No marker: either a brand-new DB or an untracked v1. Only backfill if
        # there is v1 data to convert and nothing in the strikes table yet.
        has_strikes = conn.execute("SELECT COUNT(*) FROM strikes").fetchone()[0]
        if not has_strikes:
            for u in conn.execute(
                "SELECT chat_id, user_id, strikes, last_seen FROM users WHERE strikes > 0"
            ).fetchall():
                when = u["last_seen"] or time.time()
                conn.executemany(
                    "INSERT INTO strikes (chat_id,user_id,ts) VALUES (?,?,?)",
                    [(u["chat_id"], u["user_id"], when)] * u["strikes"],
                )

    # v2 -> v3: register known chats so they appear before their next message.
    conn.execute(
        "INSERT OR IGNORE INTO chats (chat_id, title, first_seen, last_seen) "
        "SELECT DISTINCT chat_id, '', 0, 0 FROM users"
    )

    conn.execute(
        "INSERT INTO meta (key,value) VALUES ('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
