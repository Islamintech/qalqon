"""Alert coalescing.

A review queue only works if a human can read it. During a 30-account raid the
old behaviour sent 30 separate alerts, each with its own button set — burying
the admin chat at precisely the moment admins need to see what is happening.

The rule: alerts go out individually (with buttons, so they stay actionable)
until they arrive faster than `threshold` per `window`. Past that the batcher
switches to digest mode and emits ONE summary per flush interval.

A digest deliberately carries no buttons. Thirty button sets on one message is
not a thing Telegram can render, and more importantly a bulk "ban all" control
is the last thing that should exist during a raid — the digest names the users
so an admin can act deliberately with /status and /ban.
"""
import asyncio
import logging
import time

log = logging.getLogger("qalqon.alerts")


class AlertBatcher:
    def __init__(
        self,
        threshold: int = 5,
        window: float = 30.0,
        flush_interval: float = 60.0,
        max_digest_lines: int = 25,
    ) -> None:
        self._threshold = threshold
        self._window = window
        self._flush_interval = flush_interval
        self._max_lines = max_digest_lines
        self._recent: list[float] = []
        self._buffer: list[str] = []
        self._suppressed = 0
        self._flush_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def _note(self, now: float) -> int:
        self._recent.append(now)
        self._recent = [t for t in self._recent if now - t <= self._window]
        return len(self._recent)

    def batching(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        recent = [t for t in self._recent if now - t <= self._window]
        return len(recent) >= self._threshold

    async def submit(self, line: str, send, now: float | None = None) -> bool:
        """Offer one alert. Returns True if it was sent immediately, False if it
        was folded into a digest. `send` is an async callable taking the text."""
        now = time.time() if now is None else now
        async with self._lock:
            count = self._note(now)
            if count < self._threshold:
                return True  # caller sends it normally, buttons and all

            if len(self._buffer) < self._max_lines:
                self._buffer.append(line)
            else:
                self._suppressed += 1
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = asyncio.create_task(self._flush_later(send))
            return False

    async def _flush_later(self, send) -> None:
        try:
            await asyncio.sleep(self._flush_interval)
            await self.flush(send)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("digest flush failed: %s", exc)

    async def flush(self, send) -> None:
        """Emit the pending digest, if any. Also called at shutdown so nothing
        is silently lost when the bot stops mid-raid."""
        async with self._lock:
            if not self._buffer:
                return
            lines, suppressed = self._buffer, self._suppressed
            self._buffer, self._suppressed = [], 0

        body = "\n".join(f"• {line}" for line in lines)
        extra = f"\n…and {suppressed} more" if suppressed else ""
        total = len(lines) + suppressed
        await send(
            f"🌊 Qalqon digest — {total} alerts while under load\n"
            f"{body}{extra}\n\n"
            "Individual alerts are batched while volume is high. "
            "Use /status <user_id> to review one, /stats for totals."
        )

    async def close(self) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass
