"""Phase 2b: deep channel scanning via MTProto (Telethon, USER session).

Why a user session: the Bot API can't read history/files of a channel the bot
isn't a member of. A logged-in user account can read PUBLIC channels without
joining.

⚠️  RISK: automating a user account is against the spirit of Telegram's ToS and
can get the account limited or banned. Mitigations built in here:
  - lazy   : only runs for users who are ALREADY suspicious (the profile check
             only fires on non-clean messages), so we never scan the whole group
  - gentle : small message limit, FloodWait handled, no aggressive looping
  - cached : per-channel result with a TTL, so a repeat scammer isn't rescanned
  - use a DEDICATED account you don't mind losing — never your personal one
"""
import logging
import time

from .verdict import Verdict, Risk
from .file_scanner import FileScanner

log = logging.getLogger("qalqon.mtproto")

try:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError

    _TELETHON = True
except ImportError:  # bot still runs fine with the feature off
    _TELETHON = False


class MTProtoScanner:
    def __init__(
        self,
        api_id: str,
        api_hash: str,
        session: str = "qalqon_user",
        scan_limit: int = 40,
        cache_ttl: int = 6 * 3600,
        file_scanner: FileScanner | None = None,
    ) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session = session
        self._limit = scan_limit
        self._ttl = cache_ttl
        self._files = file_scanner or FileScanner()
        self._client = None
        self._cache: dict[str, tuple[float, Verdict]] = {}

    @property
    def available(self) -> bool:
        return _TELETHON and bool(self._api_id and self._api_hash)

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def start(self) -> bool:
        """Connect using an existing session. Never prompts — if the session
        isn't authorized, run scripts/telethon_login.py once first."""
        if not self.available:
            log.warning("MTProto off (telethon missing or no api_id/api_hash)")
            return False
        self._client = TelegramClient(
            self._session, int(self._api_id), self._api_hash
        )
        await self._client.connect()
        if not await self._client.is_user_authorized():
            log.error(
                "MTProto session not authorized — run "
                "`python scripts/telethon_login.py` once, then restart"
            )
            await self._client.disconnect()
            self._client = None
            return False
        log.info("MTProto scanner connected")
        return True

    async def stop(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def scan_channel(self, handle) -> Verdict:
        """Scan the most recent files in a channel. Returns the worst verdict."""
        if not self._client:
            return Verdict(Risk.CLEAN, "mtproto not connected", "channel")

        key = str(handle)
        cached = self._cache.get(key)
        if cached and (time.monotonic() - cached[0]) < self._ttl:
            return cached[1]

        try:
            entity = await self._client.get_entity(handle)
            worst = Verdict(Risk.CLEAN, "no dangerous files in channel", "channel")
            async for msg in self._client.iter_messages(entity, limit=self._limit):
                f = getattr(msg, "file", None)
                if f and f.name:
                    v = self._files.scan(f.name, f.mime_type, f.size)
                    worst = Verdict.worst(worst, v)
                    if worst.risk is Risk.RED_FLAG:
                        worst = Verdict(
                            Risk.RED_FLAG,
                            f"channel hosts '{f.name}': {v.reason}",
                            "channel",
                        )
                        break
            result = worst
        except FloodWaitError as exc:
            # Our own rate limit — never punish a user for it.
            log.warning("FloodWait %ss on %s — backing off", exc.seconds, handle)
            result = Verdict(Risk.CLEAN, "rate-limited, skipped scan", "channel")
        except Exception as exc:
            result = Verdict(Risk.CLEAN, f"channel scan error: {exc}", "channel")

        self._cache[key] = (time.monotonic(), result)
        return result
