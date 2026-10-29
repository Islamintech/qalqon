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
from dataclasses import dataclass

import httpx
from groq import AsyncGroq

from .rate_limiter import TokenBucket
from .verdict import Verdict, Risk

log = logging.getLogger("qalqon.llm")


@dataclass
class CallStats:
    """What one analysis actually cost.

    Reported on the client rather than returned inside the Verdict, because a
    Verdict is a judgement and this is bookkeeping — mixing them would put
    billing data into the object the policy reasons about.
    """

    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int = 0
    queue_ms: int = 0
    cached: bool = False
    ok: bool = True

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
  This is a normal, expected activity in these groups. Someone looking to
  BUY currency and offering to pay by card themselves is asking for nothing
  up front — that is never a scam.
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
- A vague paid "task" that never says what the work actually is, where, or
  for whom: "need help organizing movement around the city, up to 12 000",
  "simple errand in the city, good pay, details in DM". This is how couriers
  and money mules are recruited. The test is whether the KIND of work is
  named: "work at a factory, call me" is an ordinary post even with no wage
  or address, because it says what the job is. At least FIFTY_FIFTY;
  RED_FLAG if it also steers to private messages or promises high pay for
  little effort.

RUSSIAN-LANGUAGE SPAM. Members write in Russian too, so the language itself
is never a signal — but most mass spam in these groups arrives in Russian, in
a few recognisable templates. Read Russian messages for these specifically:

- Vague well-paid work with no employer, place or task named, pushed to
  private messages: "Нужны люди, доход от 5000 в день, пиши + в лс",
  "Подработка без опыта, 18+, подробности в личке", "Ищу партнёров".
- Courier and "drop" recruitment: "курьер", "закладки", "дропы", "нужен
  человек забрать и передать".
- Renting, buying or "borrowing" bank cards or accounts, or cash-out
  schemes: "аренда карт", "куплю банковскую карту", "обнал", "пробив".
- Easy-money promises: "лёгкий заработок", "заработок без вложений",
  "пассивный доход".

A Russian job post that names the work, the place and the wage ("Завтра
работа в Ансане на складе, 130 тысяч вон"), or an ordinary exchange offer,
is as normal as its Uzbek equivalent.

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
              "timeout", "timed out", "connection",
              # an empty or truncated reply; sampling again usually completes
              "json_validate_failed")


def _normalize(text: str) -> str:
    """Cache key normalization. Scammers vary spacing/case between reposts, so
    fold those away — but keep the words themselves intact."""
    return re.sub(r"\s+", " ", text.strip().lower())


# What a reply costs on top of the prompt. Measured at ~200 completion tokens
# on the recorded traffic; rounded up, because under-reserving is what the
# pacing exists to prevent and the difference is settled afterwards anyway.
_COMPLETION_ALLOWANCE = 250

# Hard cap on the reply, reasoning included. Without one Groq reserves ~1500
# completion tokens per request against the per-minute budget, so a single
# call "requests" ~2200 tokens and is refused outright (413) on a model whose
# limit is 2000 TPM — gpt-oss-safeguard-20b on the free tier.
#
# Not lower: at 500, gpt-oss at its default effort spent the whole cap on
# reasoning in 3 of 5 calls and returned nothing, which Groq rejects as
# json_validate_failed — a dropped verdict, not a cheaper one.
_MAX_COMPLETION_TOKENS = 1000

# gpt-oss reasons at "medium" unless told otherwise. A three-way label does not
# need it: at "low" the same message cost ~75 completion tokens instead of
# ~350 and gave the same answer every time, where medium wavered between
# RED_FLAG and FIFTY_FIFTY. Other models reject the parameter, so it is sent
# only to gpt-oss.
_LOW_EFFORT_PREFIXES = ("openai/gpt-oss", "gpt-oss")


def _estimate_tokens(system: str, user: str) -> int:
    """Roughly what this call will cost, BEFORE it is sent.

    Four characters to a token is crude, but the alternative is shipping a
    tokenizer for the sole purpose of pacing, and the estimate is reconciled
    against the real usage the moment the reply lands.
    """
    return (len(system) + len(user)) // 4 + 60 + _COMPLETION_ALLOWANCE


def _retryable(exc: Exception) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return any(token in blob for token in _RETRYABLE)


def _parse_json(content: str) -> dict:
    """The verdict object, even when a provider without strict JSON mode wraps
    it in a ```json fence or a sentence."""
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", content or "", re.S)
        if not match:
            raise
        return json.loads(match.group(0))


@dataclass
class Backend:
    """One model to ask. Free tiers limit each MODEL separately, so every
    backend carries its own bucket: gpt-oss-20b being out of tokens this
    minute says nothing about gpt-oss-120b."""

    label: str
    model: str
    bucket: TokenBucket
    groq: AsyncGroq | None = None
    # Any OpenAI-compatible endpoint (Cerebras, Gemini, OpenRouter...), used
    # when `groq` is None.
    base_url: str = ""
    api_key: str = ""


@dataclass
class Fallback:
    """A second provider, tried after every Groq model has failed."""

    base_url: str
    api_key: str
    model: str
    token_limit_per_minute: int = 0


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        cache_ttl: int = 900,
        cache_size: int = 512,
        max_concurrency: int = 4,
        max_attempts: int = 3,
        token_limit_per_minute: int = 0,
        fallback_models: tuple[str, ...] = (),
        fallback: Fallback | None = None,
        timeout: float = 30.0,
    ) -> None:
        groq = AsyncGroq(api_key=api_key)
        self._model = model
        self._timeout = timeout
        # Tried in order. Concurrency is not a budget: four in flight at ~0.8s
        # a call is some 290 requests a minute, against a free-tier ceiling
        # nearer eight. The buckets are what actually enforce the limit; the
        # semaphore just stops us opening sockets we cannot use.
        self._backends: list[Backend] = [
            Backend(f"groq:{m}", m, TokenBucket(token_limit_per_minute), groq=groq)
            for m in dict.fromkeys([model, *fallback_models]) if m
        ]
        if fallback and fallback.base_url and fallback.api_key and fallback.model:
            self._backends.append(Backend(
                f"fallback:{fallback.model}", fallback.model,
                TokenBucket(fallback.token_limit_per_minute),
                base_url=fallback.base_url.rstrip("/"), api_key=fallback.api_key,
            ))
        self._bucket = self._backends[0].bucket
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
        # Refreshed on every analyze(); the Model reads it and persists it.
        self.last: CallStats = CallStats()

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
        """One analysis, falling through the backends in order. Raises only if
        every one of them failed."""
        started = time.perf_counter()
        errors: list[str] = []
        self._last_attempts = 0
        for i, backend in enumerate(self._backends):
            last_backend = i == len(self._backends) - 1
            try:
                return await self._call_backend(
                    backend, user_content, started, patient=last_backend
                )
            except Exception as exc:
                errors.append(f"{backend.label}: {exc}")
                if not last_backend:
                    log.warning("llm %s failed (%s) — trying %s",
                                backend.label, exc, self._backends[i + 1].label)
        raise RuntimeError(" | ".join(errors) or "llm call failed")

    async def _call_backend(
        self, backend: Backend, user_content: str, started: float, patient: bool
    ) -> Verdict:
        """One backend, with retries. Only the LAST backend waits: with another
        model to try, a rate limit means "ask the next one now", not "back off
        and ask this one again in four seconds"."""
        estimate = _estimate_tokens(SYSTEM_PROMPT, user_content)
        if not patient and not backend.bucket.try_acquire(estimate):
            raise RuntimeError("local token budget for this minute is spent")
        last: Exception | None = None
        attempts = self._max_attempts if patient else 1
        for attempt in range(attempts):
            self._last_attempts += 1
            try:
                if patient:
                    # Wait for room rather than discover the ceiling as a
                    # 429. A call delayed two seconds succeeds; the same call
                    # sent now is three retries and a verdict marked degraded.
                    await backend.bucket.acquire(estimate)
                async with self._sem:
                    self.calls += 1
                    content, stats = await self._complete(backend, user_content)
                stats.latency_ms = int((time.perf_counter() - started) * 1000)
                self.last = stats
                backend.bucket.charge(
                    stats.prompt_tokens + stats.completion_tokens - estimate
                )
                data = _parse_json(content)
                risk = Risk(str(data.get("risk", "CLEAN")).upper())
                return Verdict(risk, str(data.get("reason", ""))[:200], "llm")
            except Exception as exc:
                last = exc
                if attempt + 1 >= attempts or not _retryable(exc):
                    break
                # Jittered backoff so a raid's worth of retries don't resynchronize
                # into another thundering herd.
                delay = (2**attempt) + random.uniform(0, 0.5)
                log.warning(
                    "llm %s attempt %s/%s failed (%s) — retrying in %.1fs",
                    backend.label, attempt + 1, attempts, exc, delay,
                )
                await asyncio.sleep(delay)
        raise last if last else RuntimeError("llm call failed")

    async def _complete(self, backend: Backend, user_content: str):
        """Send the request; return the reply text and what it cost."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        effort = (
            {"reasoning_effort": "low"}
            if backend.model.startswith(_LOW_EFFORT_PREFIXES) else {}
        )
        if backend.groq is not None:
            resp = await backend.groq.chat.completions.create(
                model=backend.model,
                temperature=0,
                max_tokens=_MAX_COMPLETION_TOKENS,
                response_format={"type": "json_object"},
                messages=messages,
                # Through extra_body: the pinned SDK predates the parameter.
                extra_body=effort or None,
            )
            usage = getattr(resp, "usage", None)
            details = getattr(usage, "completion_tokens_details", None)
            return resp.choices[0].message.content, CallStats(
                model=getattr(resp, "model", backend.model),
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                reasoning_tokens=getattr(details, "reasoning_tokens", 0) or 0,
                queue_ms=int((getattr(usage, "queue_time", 0) or 0) * 1000),
            )

        # Plain OpenAI-compatible HTTP: one shape fits Cerebras, Gemini and
        # OpenRouter, without a second SDK to keep in step.
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            r = await http.post(
                f"{backend.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {backend.api_key}"},
                json={
                    "model": backend.model,
                    "temperature": 0,
                    "max_completion_tokens": _MAX_COMPLETION_TOKENS,
                    "response_format": {"type": "json_object"},
                    "messages": messages,
                    **effort,
                },
            )
            r.raise_for_status()
            data = r.json()
        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        return data["choices"][0]["message"]["content"], CallStats(
            model=data.get("model") or backend.model,
            prompt_tokens=usage.get("prompt_tokens") or 0,
            completion_tokens=usage.get("completion_tokens") or 0,
            reasoning_tokens=details.get("reasoning_tokens") or 0,
        )

    async def analyze(self, text: str, context: str = "") -> Verdict:
        # The context is part of the QUESTION, so it belongs in the key rather
        # than disqualifying the answer from being stored. Keying on text alone
        # would let a long-standing member's verdict answer for a brand-new
        # account saying the same thing; refusing to cache whenever a context
        # was supplied — the previous behaviour — meant never caching at all,
        # since the model always supplies one. A raid is many NEW accounts
        # posting one line, so their context is identical too, which is
        # precisely when this has to work.
        key = hashlib.sha256(
            json.dumps([_normalize(text), _normalize(context)]).encode()
        ).hexdigest()
        cached = self._cache_get(key)
        if cached is not None:
            self.last = CallStats(model=self._model, cached=True)
            return Verdict(cached.risk, f"{cached.reason} (cached)", "llm")

        user_content = f"{context}\n\nMESSAGE:\n{text}" if context else text
        try:
            verdict = await self._call(user_content)
            self._consecutive_failures = 0
            self._cache_put(key, verdict)
            return verdict
        except Exception as exc:
            self.failures += 1
            self._consecutive_failures += 1
            self.last = CallStats(model=self._model, ok=False)
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
