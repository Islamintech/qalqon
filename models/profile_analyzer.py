"""Second line of defense: does the SENDER look like a scammer?

Phase 2 composes three signals into one profile verdict:
  - bio text            (cheap keyword check)
  - profile photo       (VisionClient -> free HF NSFW classifier)
  - linked channel      (ChannelAnalyzer -> Bot API metadata)
Takes the worst of them. Any component can fail without banning anyone.
"""
from telegram import Bot

from .verdict import Verdict, Risk
from .vision_client import VisionClient
from .channel_analyzer import ChannelAnalyzer

SUSPICIOUS_BIO_TERMS = [
    "invest", "crypto signals", "forex", "18+", "onlyfans",
    "trader", "guaranteed profit", "dm for", "click link",
]


class ProfileAnalyzer:
    def __init__(
        self,
        vision: VisionClient | None = None,
        channel: ChannelAnalyzer | None = None,
    ) -> None:
        self._vision = vision
        self._channel = channel or ChannelAnalyzer()

    async def analyze(self, bot: Bot, user_id: int) -> Verdict:
        """Every sub-check ALWAYS contributes a verdict, even a clean one, and
        each names its own source ("bio" / "photo" / "channel") rather than all
        calling themselves "profile".

        The reason is the alert breakdown: a check that ran and found nothing is
        information, and it must be distinguishable from a check that never ran.
        Appending only on a hit made a clean bio and a skipped bio look
        identical to whoever is reviewing the case.
        """
        verdicts: list[Verdict] = []

        # --- bio -------------------------------------------------------------
        try:
            chat = await bot.get_chat(user_id)
            bio = (getattr(chat, "bio", None) or "").lower()
            hits = [t for t in SUSPICIOUS_BIO_TERMS if t in bio]
            if hits:
                verdicts.append(
                    Verdict(Risk.RED_FLAG, f"bio: {', '.join(hits)}", "bio")
                )
            elif bio:
                verdicts.append(Verdict(Risk.CLEAN, "bio has no scam terms", "bio"))
            else:
                verdicts.append(Verdict(Risk.CLEAN, "no bio set", "bio"))
        except Exception as exc:
            # Could not read it — not evidence of anything, but say so.
            verdicts.append(
                Verdict(Risk.CLEAN, f"bio unreadable: {exc}", "bio", degraded=True)
            )

        # --- profile photo -> vision ----------------------------------------
        try:
            photos = await bot.get_user_profile_photos(user_id, limit=1)
            if photos.total_count == 0:
                verdicts.append(Verdict(Risk.FIFTY_FIFTY, "no profile photo", "photo"))
            elif self._vision is None:
                verdicts.append(
                    Verdict(Risk.CLEAN, "photo present, screening off", "photo")
                )
            else:
                largest = photos.photos[0][-1]  # highest-res size
                tg_file = await bot.get_file(largest.file_id)
                img = bytes(await tg_file.download_as_bytearray())
                verdicts.append(await self._vision.classify_image(img))
        except Exception as exc:
            verdicts.append(
                Verdict(Risk.CLEAN, f"photo unreadable: {exc}", "photo", degraded=True)
            )

        # --- linked channel --------------------------------------------------
        verdicts.append(await self._channel.analyze(bot, user_id))

        return Verdict.worst(*verdicts)
