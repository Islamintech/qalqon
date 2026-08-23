"""Inspects a user's linked personal channel.

Bot API (always on): reads chat.personal_chat — the channel a user pinned to
their profile — and checks its public title/description. Having a linked
channel is NORMAL, so presence alone is not a red flag.

MTProto (phase 2b, optional): if an MTProtoScanner is injected AND connected,
also deep-scans the channel's recent files for fake APKs etc. This only ever
runs on already-suspicious users, because the profile check itself only fires
on non-clean messages.
"""
from telegram import Bot

from .verdict import Verdict, Risk

SUSPICIOUS_DESC_TERMS = [
    "invest", "signal", "forex", "crypto", "profit", "airdrop",
    "apk", "download app", "verify wallet", "guaranteed", "18+",
]


class ChannelAnalyzer:
    def __init__(self, mtproto=None) -> None:
        self._mtproto = mtproto

    async def analyze(self, bot: Bot, user_id: int) -> Verdict:
        try:
            chat = await bot.get_chat(user_id)
            personal = getattr(chat, "personal_chat", None)
            if not personal:
                return Verdict(Risk.CLEAN, "no linked channel", "channel")

            handle = personal.username or personal.id
            desc = (getattr(personal, "description", None) or "").lower()
            reasons = [f"linked channel @{handle}"]
            risk = Risk.CLEAN  # linking a channel is normal on its own
            for term in SUSPICIOUS_DESC_TERMS:
                if term in desc:
                    reasons.append(f"channel desc has '{term}'")
                    risk = Risk.RED_FLAG
            meta = Verdict(risk, "; ".join(reasons), "channel")

            # phase 2b: deep file scan of the channel, if a user session exists
            if self._mtproto and self._mtproto.connected:
                deep = await self._mtproto.scan_channel(handle)
                return Verdict.worst(meta, deep)
            return meta
        except Exception as exc:
            return Verdict(Risk.CLEAN, f"channel check error: {exc}", "channel")
