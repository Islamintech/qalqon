"""Proof of life.

A moderation bot that has silently died is worse than no bot at all: the groups
look protected, nobody is watching them, and the failure is invisible precisely
because a dead bot generates no alerts. Quiet means "nothing bad happened" and
"I stopped working" at the same time, and those must be distinguishable.

So the bot says so periodically. The signal you act on is the ABSENCE of the
daily ping — that is why it is sent on a fixed schedule regardless of activity,
and why a quiet day still sends one. (Contrast the digest, which deliberately
stays silent when nothing happened: a digest is a report about events, this is
a report about the process.)

Three messages:
  startup   — sent once when it comes up, so a restart loop is visible as a
              stream of these rather than as silence
  daily     — "still here", plus what it has done since the last one
  shutdown  — sent on a clean stop, so an expected stop is distinguishable
              from a crash
"""
import asyncio
import logging
import time

log = logging.getLogger("scamguard.heartbeat")


def _duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class Heartbeat:
    def __init__(self, store, interval: float = 86400.0) -> None:
        self._store = store
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._started_at = time.time()
        self._baseline: dict[str, int] = {}

    async def _snapshot(self) -> dict[str, int]:
        try:
            stats = await self._store.stats()
            return dict(stats.get("actions", {}))
        except Exception as exc:
            log.warning("could not read stats for heartbeat: %s", exc)
            return {}

    def _delta(self, now: dict[str, int]) -> str:
        changes = {
            action: count - self._baseline.get(action, 0)
            for action, count in now.items()
            if count - self._baseline.get(action, 0) > 0
        }
        if not changes:
            return "no moderation actions in this period"
        return ", ".join(f"{n}× {action}" for action, n in sorted(changes.items()))

    async def startup(self, send, detail: str = "") -> None:
        self._started_at = time.time()
        self._baseline = await self._snapshot()
        try:
            await send(f"✅ ScamGuard started\n{detail}" if detail else "✅ ScamGuard started")
        except Exception as exc:
            log.warning("startup notice failed: %s", exc)

    async def shutdown(self, send) -> None:
        """Only reached on a CLEAN stop — so if you never see this, it crashed
        or the machine went away."""
        try:
            await send(
                f"⏹ ScamGuard stopping (clean shutdown)\n"
                f"uptime {_duration(time.time() - self._started_at)}"
            )
        except Exception as exc:
            log.warning("shutdown notice failed: %s", exc)

    async def beat(self, send) -> None:
        now = await self._snapshot()
        body = (
            f"💚 ScamGuard still running\n"
            f"uptime {_duration(time.time() - self._started_at)}\n"
            f"since last check: {self._delta(now)}\n\n"
            "If this stops arriving, the bot is down."
        )
        self._baseline = now
        await send(body)

    async def start(self, send) -> None:
        if self._task and not self._task.done():
            return

        async def _loop() -> None:
            while True:
                try:
                    await asyncio.sleep(self._interval)
                    await self.beat(send)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # A failed ping must never take the moderator down with it.
                    log.warning("heartbeat failed: %s", exc)

        self._task = asyncio.create_task(_loop())
        log.info("heartbeat started (every %.0fs)", self._interval)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
