"""Per-token prices, fetched from Groq's own API rather than hard-coded.

Groq's /v1/models response carries a `pricing` block per model, so the numbers
on the dashboard come from the same place that bills you. A table of prices
copied into source is wrong the day after a price change, and nobody notices
because the figures still look plausible.

Cached in memory for an hour and stored in the database's meta table, so the
dashboard still shows a cost after a restart or while the API is unreachable —
labelled as a cached figure rather than silently stale.
"""
import json
import logging
import time

import httpx

log = logging.getLogger("qalqon.web.pricing")

MODELS_URL = "https://api.groq.com/openai/v1/models"
TTL = 3600.0

_cache: dict[str, tuple[float, dict]] = {}


def fetch(api_key: str) -> dict[str, dict]:
    """{model_id: {"prompt": $/token, "completion": $/token}}. Empty on failure —
    a missing price must show as "unknown", never as zero, or the dashboard
    would quietly report every deployment as free."""
    hit = _cache.get("all")
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    if not api_key:
        return {}
    try:
        r = httpx.get(
            MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=15
        )
        r.raise_for_status()
        out = {}
        for m in r.json().get("data", []):
            p = m.get("pricing") or {}
            if p.get("prompt") is not None:
                out[m["id"]] = {
                    "prompt": float(p.get("prompt", 0)),
                    "completion": float(p.get("completion", 0)),
                }
        _cache["all"] = (time.time(), out)
        return out
    except Exception as exc:
        log.warning("could not fetch model pricing: %s", exc)
        return hit[1] if hit else {}


def cost(model: str, prompt_tokens: int, completion_tokens: int,
         prices: dict) -> float | None:
    p = prices.get(model)
    if not p:
        return None
    return prompt_tokens * p["prompt"] + completion_tokens * p["completion"]


def money(value: float | None) -> str:
    """Format a cost honestly at this scale.

    Moderating a hundred thousand messages costs single-digit dollars, so
    rounding to cents would print $0.00 for a month's work and make the figure
    look broken. Small amounts keep their significant digits.
    """
    if value is None:
        return "—"
    if value == 0:
        return "$0"
    if value < 0.01:
        return f"${value:.4f}"
    if value < 1:
        return f"${value:.3f}"
    return f"${value:,.2f}"


def per_thousand(model: str, summary: dict, prices: dict) -> float | None:
    """Cost per 1,000 analysed messages — the figure that lets you project."""
    billed = summary.get("billed") or 0
    if not billed:
        return None
    total = cost(model, summary["prompt_tokens"], summary["completion_tokens"], prices)
    if total is None:
        return None
    return total / billed * 1000


def save_snapshot(conn_exec, prices: dict) -> None:
    """Best-effort persistence, so a restart does not blank the cost column."""
    try:
        conn_exec(
            "INSERT INTO meta (key,value) VALUES ('pricing',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(prices),),
        )
    except Exception as exc:
        log.warning("could not cache pricing: %s", exc)
