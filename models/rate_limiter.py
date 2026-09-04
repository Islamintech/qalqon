"""Pace outgoing model calls against the account's tokens-per-minute ceiling.

The semaphore in LLMClient caps how many calls are in flight, which is not the
same thing as how many are allowed. At roughly 0.8s a call, four in flight
permits some 290 requests a minute — against a free-tier budget nearer eight.
So the concurrency cap protected sockets while the budget went unenforced, and
the bot found its limit the only remaining way: by being 429'd, in the busy
minute when it could least afford to lose the model.

A bucket rather than a fixed delay, because the limit is per MINUTE. A group
is quiet for long stretches and then everybody replies at once; a fixed gap
would throttle the quiet stretch for no reason and still not describe the
ceiling. A bucket lets the burst run until the allowance is actually gone.

Credit does not accumulate past one minute's worth. Saving up an hour of
silence would buy an hour-sized burst, which the provider will refuse — the
ceiling is a rate, not a quota.

Waiting is the whole point: a call delayed by two seconds is a call that
succeeds, where the same call sent immediately is a 429, three retries, and a
verdict marked degraded.
"""
import asyncio
import logging
import time

log = logging.getLogger("qalqon.ratelimit")

# Slack for floating-point remainder, in tokens. Far below one token, so
# it can never hand out budget that was not earned.
_EPSILON = 1e-6
# No wait shorter than this is worth the wake-up.
_MIN_WAIT = 0.005


class TokenBucket:
    """Tokens-per-minute pacing. `acquire(n)` returns once n tokens fit.

    `clock` and `sleep` are injectable so the tests can run a minute of
    traffic without spending a minute.
    """

    def __init__(
        self,
        limit_per_minute: int,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    ) -> None:
        self._limit = max(int(limit_per_minute), 0)
        self._clock = clock
        self._sleep = sleep
        self._available = float(self._limit)
        self._checked = clock()
        self._lock = asyncio.Lock()
        self.waits = 0
        self.tokens_spent = 0

    @property
    def enabled(self) -> bool:
        """0 disables pacing — for an unmetered plan, or a limit nobody knows.
        Throttling to a halt on a guess would be worse than not pacing."""
        return self._limit > 0

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._checked
        self._checked = now
        if elapsed > 0:
            # Capped at the ceiling: the limit is a rate, not a quota that
            # quiet periods top up.
            self._available = min(
                float(self._limit), self._available + elapsed * self._limit / 60.0
            )

    def charge(self, tokens: int) -> None:
        """Reconcile an estimate against the real cost, without waiting.

        A call has to reserve budget BEFORE it is sent, when the true cost is
        not yet known, so the reservation is an estimate. This settles the
        difference afterwards: a negative amount refunds an over-estimate, and
        a positive one can push the allowance below zero, which simply makes
        the next caller wait a little longer. Never blocks, because the call
        it is accounting for has already happened.
        """
        if not self.enabled or not tokens:
            return
        self._refill()
        self._available = min(float(self._limit), self._available - float(tokens))
        self.tokens_spent += int(tokens)

    async def acquire(self, tokens: int) -> None:
        if not self.enabled:
            return
        # A single call bigger than the whole per-minute budget can never fit,
        # so waiting for room would block forever. Let it through and let the
        # provider decide — one oversized call is not the case this guards.
        want = min(float(max(tokens, 0)), float(self._limit))
        async with self._lock:
            while True:
                self._refill()
                # EPSILON, not a bare >=. Refilling for exactly the deficit can
                # land a hair short of it in floating point, so the next delay
                # is ~1e-16, the clock does not move enough to notice, and this
                # loop never exits — holding its lock with the event loop
                # pinned, which stalls every other message in the bot.
                if self._available + _EPSILON >= want:
                    self._available -= want
                    self.tokens_spent += int(tokens)
                    return
                deficit = want - self._available
                # Floored: a sub-millisecond sleep is a busy-wait in a costume,
                # and rounding can always leave a sliver behind.
                delay = max(deficit * 60.0 / self._limit, _MIN_WAIT)
                self.waits += 1
                log.debug("pacing: waiting %.2fs for %s tokens", delay, tokens)
                await self._sleep(delay)
