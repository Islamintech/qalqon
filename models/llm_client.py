"""Wraps Groq. Sends the message text, gets back a structured verdict.
We force JSON output and parse it defensively so a malformed reply can never
crash the bot.

Three controls, because Groq's free tier is rate-limited and a raid is exactly
when we cannot afford to lose the model:

  - CACHE       identical text is answered from an in-process TTL cache, so a
                spammer posting the same line 30 times costs one call
  - CONCURRENCY a semaphore caps in-flight calls. 20 accounts posting at once
                used to fire 20 simultaneous requests and rate-limit ourselves
  - BACKOFF     429s and 5xx are retried with exponential backoff instead of
                being swallowed as "clean"

When the model genuinely cannot be reached, `analyze` returns a verdict marked
`degraded=True`. That is the important part: a CLEAN we never actually earned
must be distinguishable from a CLEAN the model returned, so the controller can
fall back to keyword-only moderation and tell the admins detection is impaired
— rather than silently passing everything during an outage.
"""
import asyncio
import hashlib
import json
import logging
import random
import re
import time

from groq import AsyncGroq

from .verdict import Verdict, Risk

log = logging.getLogger("qalqon.llm")

SYSTEM_PROMPT = """You are a moderation assistant for Telegram groups whose
members are Uzbek workers living in South Korea. Messages arrive in Uzbek,
Russian, Korean or English — judge them all by the same standard, and never let
translated or informal phrasing count against a message.

WHAT IS ORDINARY IN THESE GROUPS. Never raise risk for the topic alone:

- Work announcements. "There is work tomorrow in Ansan, 3 people needed,
  130,000 won a day, message me if you are free." Naming a wage, a factory, a
  district or a shift, and asking people to write or call, is how ordinary
  recruitment happens here.
- Asking whether anyone is free, available, or looking for a shift.
- Person-to-person currency exchange between Korean won (KRW) and Uzbek so'm
  (UZS): offering to exchange, asking today's rate, stating how much one holds
  ("who needs so'm? I have 5 million"), and settling by bank or card transfer.
  This is a normal, expected activity in these groups.
- Sharing a phone number, or asking to continue privately, for either of the
  above.

WHAT MAKES SOMETHING A SCAM. The subject is never the signal — the ASK is:

- Money or documents demanded UP FRONT against a promise of something later:
  a deposit for a visa, a commission to "find you a job", a fee before
  delivery.
- In an exchange, pressure for the other person to send first: "you transfer,
  then I will send", or refusing to use a mutually safe method.
- Guaranteed profit, investment offers, fixed daily percentage returns.
- A rate far better than the market, artificial urgency, "only a few places
  left".
- Sexual solicitation, or steering strangers to a profile or channel to see
  something.
- Links imitating a bank, exchange or government site; requests for card
  numbers, passwords or verification codes.

RISK LEVELS
RED_FLAG    — clearly matches one of the scam patterns above.
FIFTY_FIFTY — genuinely ambiguous and needs a human. Do NOT use this merely
              because a message concerns money, work, or an exchange.
CLEAN       — normal conversation, including every ordinary case listed above.

You may be given context about the sender (how long they have been in the
group, prior strikes) and the links in their message. Treat it as a prior, not
as proof: a brand-new account making an up-front-payment offer is more
suspicious than a long-standing member using the same words. Never raise risk
on context alone — the MESSAGE must justify the verdict.

Respond with ONLY a JSON object, no prose, no markdown:
{"risk": "RED_FLAG" | "FIFTY_FIFTY" | "CLEAN", "reason": "<short reason, in English>"}"""


# Errors worth retrying: rate limits and transient server-side failures.
_RETRYABLE = ("429", "rate limit", "rate_limit", "500", "502", "503", "504",
              "timeout", "timed out", "connection")


def _normalize(text: str) -> str:
    """Cache key normalization. Scammers vary spacing/case between reposts, so
    fold those away — but keep the words themselves intact."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _retryable(exc: Exception) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return any(token in blob for token in _RETRYABLE)


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        cache_ttl: int = 900,
        cache_size: int = 512,
        max_concurrency: int = 4,
        max_attempts: int = 3,
    ) -> None:
        self._client = AsyncGroq(api_key=api_key)
        self._model = model
        self._ttl = cache_ttl
        self._max = cache_size
        self._cache: dict[str, tuple[float, Verdict]] = {}
        self._sem = asyncio.Semaphore(max_concurrency)
        self._max_attempts = max(max_attempts, 1)
        self.calls = 0
        self.cache_hits = 0
        self.failures = 0
        self._consecutive_failures = 0
        self._last_attempts = 0

    @property
    def degraded(self) -> bool:
        """True once calls are failing repeatedly — the controller uses this to
        warn admins that moderation is running on keywords alone."""
        return self._consecutive_failures >= 3

    def _cache_get(self, key: str) -> Verdict | None:
        hit = self._cache.get(key)
        if hit and (time.monotonic() - hit[0]) < self._ttl:
            self.cache_hits += 1
            return hit[1]
        self._cache.pop(key, None)
        return None

    def _cache_put(self, key: str, verdict: Verdict) -> None:
        if len(self._cache) >= self._max:
            # Cheap eviction: drop the oldest quarter rather than tracking LRU.
            for old in sorted(self._cache, key=lambda k: self._cache[k][0])[
                : self._max // 4 or 1
            ]:
                self._cache.pop(old, None)
        self._cache[key] = (time.monotonic(), verdict)

    async def _call(self, user_content: str) -> Verdict:
        """One analysis with retries. Raises if every attempt failed."""
        last: Exception | None = None
        self._last_attempts = 0
        for attempt in range(self._max_attempts):
            self._last_attempts = attempt + 1
            try:
                async with self._sem:
                    self.calls += 1
                    resp = await self._client.chat.completions.create(
                        model=self._model,
                        temperature=0,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                    )
                data = json.loads(resp.choices[0].message.content)
                risk = Risk(str(data.get("risk", "CLEAN")).upper())
                return Verdict(risk, str(data.get("reason", ""))[:200], "llm")
            except Exception as exc:
                last = exc
                if attempt + 1 >= self._max_attempts or not _retryable(exc):
                    break
                # Jittered backoff so a raid's worth of retries don't resynchronize
                # into another thundering herd.
                delay = (2**attempt) + random.uniform(0, 0.5)
                log.warning(
                    "llm attempt %s/%s failed (%s) — retrying in %.1fs",
                    attempt + 1, self._max_attempts, exc, delay,
                )
                await asyncio.sleep(delay)
        raise last if last else RuntimeError("llm call failed")

    async def analyze(self, text: str, context: str = "") -> Verdict:
        key = hashlib.sha256(_normalize(text).encode()).hexdigest()
        cached = self._cache_get(key)
        if cached is not None:
            return Verdict(cached.risk, f"{cached.reason} (cached)", "llm")

        user_content = f"{context}\n\nMESSAGE:\n{text}" if context else text
        try:
            verdict = await self._call(user_content)
            self._consecutive_failures = 0
            # Only cache verdicts that didn't depend on this user's context,
            # otherwise one user's history would colour another's result.
            if not context:
                self._cache_put(key, verdict)
            return verdict
        except Exception as exc:
            self.failures += 1
            self._consecutive_failures += 1
            log.error(
                "llm unavailable after %s attempt(s) (%s consecutive): %s",
                getattr(self, "_last_attempts", 1), self._consecutive_failures, exc,
            )
            # Fail safe on the ACTION (never auto-punish on our own outage) but
            # not silently: degraded=True tells the controller this CLEAN was
            # never actually earned.
            return Verdict(
                risk=Risk.CLEAN,
                reason=f"llm unavailable: {exc}",
                source="llm",
                degraded=True,
            )
