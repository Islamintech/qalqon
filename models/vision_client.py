"""Profile-photo screening via Hugging Face Inference Providers.

Model: Falconsai/nsfw_image_detection (image-classification) — this is HF's own
documented example model for the task, and returns
[{"label":"normal","score":..},{"label":"nsfw","score":..}].

Two things about this endpoint were found the hard way, by calling it:

1. HF folded serverless inference into "Inference Providers". The old
   `api-inference.huggingface.co` host no longer resolves AT ALL — DNS fails —
   so code still pointing there fails 100% of the time. Requests now go to
   https://router.huggingface.co/hf-inference/models/<model>

2. The router rejects a raw-bytes body that arrives without a Content-Type
   ("No content type provided and no default one configured"). It must be set
   explicitly; a valid token is not enough.

The token must also be a FINE-GRAINED token with the "Make calls to Inference
Providers" permission — an ordinary read token gets a 401.

Because that URL moved once, it can move again. So a failure here is reported
as `degraded` rather than silently returning CLEAN: a screening step that is
quietly dead is worse than one switched off, because it still looks like it is
working.
"""
import asyncio
import logging

import httpx

from .verdict import Verdict, Risk

log = logging.getLogger("scamguard.vision")

HF_NSFW_MODEL = "Falconsai/nsfw_image_detection"
HF_ROUTER = "https://router.huggingface.co/hf-inference/models"

# Transient conditions worth one retry: cold starts and gateway hiccups.
_RETRY_STATUS = {429, 502, 503, 504}

# Telegram hands us JPEG for most profile photos but PNG for some, so sniff the
# magic bytes rather than assuming — see note 2 in the module docstring.
_MAGIC = (
    (bytes([0x89]) + b"PNG\r\n" + bytes([0x1A, 0x0A]), "image/png"),
    (bytes([0xFF, 0xD8, 0xFF]), "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
)


def _content_type(image_bytes: bytes) -> str:
    for magic, mime in _MAGIC:
        if image_bytes.startswith(magic):
            return mime
    return "image/jpeg"  # Telegram's usual format


class VisionClient:
    def __init__(
        self,
        hf_token: str,
        model: str = HF_NSFW_MODEL,
        nsfw_threshold: float = 0.75,
        timeout: float = 30.0,
    ) -> None:
        self._url = f"{HF_ROUTER}/{model}"
        self._headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}
        self._threshold = nsfw_threshold
        self._timeout = timeout
        self.failures = 0

    async def classify_image(self, image_bytes: bytes) -> Verdict:
        try:
            results = await self._post(image_bytes)
        except Exception as exc:
            self.failures += 1
            log.error("vision unavailable: %s", exc)
            # Fail safe on the ACTION — a vision outage must never ban anyone —
            # but NOT silently. degraded=True keeps "we looked and it was fine"
            # separate from "we never got to look".
            return Verdict(
                Risk.CLEAN, f"vision unavailable: {exc}", "vision", degraded=True
            )

        try:
            scores = {item["label"].lower(): float(item["score"]) for item in results}
        except (TypeError, KeyError, ValueError) as exc:
            self.failures += 1
            log.error("unexpected vision response %r: %s", results, exc)
            return Verdict(
                Risk.CLEAN, f"vision response unreadable: {exc}", "vision",
                degraded=True,
            )

        nsfw = scores.get("nsfw", 0.0)
        if nsfw >= self._threshold:
            return Verdict(Risk.RED_FLAG, f"nsfw photo score={nsfw:.2f}", "vision")
        if nsfw >= self._threshold * 0.6:
            return Verdict(
                Risk.FIFTY_FIFTY, f"borderline photo score={nsfw:.2f}", "vision"
            )
        return Verdict(Risk.CLEAN, f"photo ok score={nsfw:.2f}", "vision")

    async def _post(self, image_bytes: bytes) -> list:
        """One classification, with a single retry for cold starts. Raises on
        failure so the caller can mark the verdict degraded."""
        last: Exception | None = None
        headers = {**self._headers, "Content-Type": _content_type(image_bytes)}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(2):
                try:
                    r = await client.post(
                        self._url, headers=headers, content=image_bytes
                    )
                    if r.status_code in _RETRY_STATUS and attempt == 0:
                        # A cold model returns 503 while it loads.
                        log.info("vision %s — retrying once", r.status_code)
                        await asyncio.sleep(5)
                        continue
                    if r.status_code == 401:
                        raise RuntimeError(
                            "401 — HF_TOKEN needs to be a fine-grained token "
                            "with the 'Make calls to Inference Providers' "
                            "permission"
                        )
                    r.raise_for_status()
                    return r.json()
                except Exception as exc:
                    last = exc
                    if attempt == 1:
                        break
        raise last if last else RuntimeError("vision call failed")
