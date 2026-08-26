"""Periodic per-chat summaries of what the bot did on its own.

Across many groups, one live alert per action is unreadable — and unreadable
means unread, which is worse than silence because it looks like oversight is
happening when it is not. Routine actions accumulate here and go out as one
message per chat per interval.

Grouped BY CHAT rather than chronologically: with twenty groups, a flat
timeline tells you nothing about which community has a problem. "Crypto Chat:
14 bans this morning" is actionable; the same fourteen lines interleaved with
other groups' traffic is not.

This is deliberately separate from AlertBatcher. That one is a pressure valve —
it kicks in only when LIVE alerts arrive faster than a human can read them.
This one is the normal path for things nobody needs to see immediately.
"""
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

log = logging.getLogger("qalqon.digest")


@dataclass
class ChatDigest:
    chat_id: int
    title: str = ""
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    lines: list[str] = field(default_factory=list)
    suppressed: int = 0

    def label(self) -> str:
        return f'"{self.title}" ({self.chat_id})' if self.title else str(self.chat_id)


class DigestReporter:
    def __init__(self, interval: float = 21600.0, max_lines_per_chat: int = 15) -> None:
        self._interval = interval
        self._max_lines = max_lines_per_chat
        self._chats: dict[int, ChatDigest] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._since = time.time()

    @property
    def pending(self) -> int:
        return sum(sum(c.counts.values()) for c in self._chats.values())

    async def add(
        self, chat_id: int, title: str, action: str, username: str,
        user_id: int, reason: str,
    ) -> None:
        async with self._lock:
            entry = self._chats.setdefault(chat_id, ChatDigest(chat_id))
            if title:
                entry.title = title
            entry.counts[action] += 1
            if len(entry.lines) < self._max_lines:
                who = f"@{username}" if username else str(user_id)
                entry.lines.append(f"{action} {who} — {reason[:90]}")
            else:
                entry.suppressed += 1

    def _render(self) -> str | None:
        if not self._chats:
            return None
        hours = max((time.time() - self._since) / 3600.0, 0)
        out = [f"📋 Qalqon digest — last {hours:.1f}h"]
        for entry in sorted(
            self._chats.values(), key=lambda c: -sum(c.counts.values())
        ):
            summary = ", ".join(
                f"{n}× {action}" for action, n in sorted(entry.counts.items())
            )
            out.append(f"\n{entry.label()}\n  {summary}")
            out += [f"  • {line}" for line in entry.lines]
            if entry.suppressed:
                out.append(f"  …and {entry.suppressed} more")
        out.append(
            "\nThese were handled automatically. Use /status <chat_id> <user_id> "
            "to inspect one, or /forgive to undo a strike."
        )
        return "\n".join(out)

    async def flush(self, send) -> bool:
        """Emit the digest if anything is pending. Returns whether it sent."""
        async with self._lock:
            body = self._render()
            self._chats.clear()
            self._since = time.time()
        if body is None:
            return False
        await send(body)
        return True

    async def start(self, send) -> None:
        if self._task and not self._task.done():
            return

        async def _loop() -> None:
            while True:
                try:
                    await asyncio.sleep(self._interval)
                    await self.flush(send)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # A digest failure must never take the moderator down.
                    log.warning("digest loop error: %s", exc)

        self._task = asyncio.create_task(_loop())
        log.info("digest reporter started (every %.0fs)", self._interval)

    async def stop(self, send) -> None:
        """Cancel the timer and emit whatever is pending, so a restart does not
        silently discard a partial period."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        try:
            await self.flush(send)
        except Exception as exc:
            log.warning("final digest failed: %s", exc)
