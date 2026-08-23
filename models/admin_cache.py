"""Who are the admins of this chat?

Group admins are skipped by the moderator, because Telegram will not let a bot
delete or ban them anyway — so an alert about an admin is an alert nobody can
act on. Unactionable alerts are worse than no alert: they train whoever reads
the queue to ignore it.

COST: the naive implementation calls get_chat_member(chat_id, user_id) once per
message, which is an API round-trip on every single message in the group. This
fetches the whole admin list for a chat in ONE call and caches it, so the cost
is one request per chat per TTL no matter how busy the chat is.

STALENESS: a demoted admin keeps the exemption until the cache expires. That is
an acceptable window for a rare event, and `invalidate()` exists for when we
learn the list changed.

FAILURE: if the list cannot be fetched we report "not an admin", so the message
gets moderated normally. Failing the other way would silently switch moderation
off for everyone whenever Telegram hiccups — a detector that quietly stops
detecting is the failure mode this whole project keeps designing against.
"""
import logging
import time

log = logging.getLogger("scamguard.admins")


class AdminCache:
    def __init__(self, ttl: float = 300.0) -> None:
        self._ttl = ttl
        self._cache: dict[int, tuple[float, frozenset[int]]] = {}

    def invalidate(self, chat_id: int) -> None:
        self._cache.pop(chat_id, None)

    async def admin_ids(self, bot, chat_id: int) -> frozenset[int]:
        hit = self._cache.get(chat_id)
        if hit and (time.monotonic() - hit[0]) < self._ttl:
            return hit[1]
        try:
            members = await bot.get_chat_administrators(chat_id)
            ids = frozenset(m.user.id for m in members)
        except Exception as exc:
            # Do not cache a failure — retry on the next message rather than
            # locking in an empty list for the whole TTL.
            log.warning("could not read admins of %s: %s", chat_id, exc)
            return frozenset()
        self._cache[chat_id] = (time.monotonic(), ids)
        log.info("cached %s admins for chat %s", len(ids), chat_id)
        return ids

    async def is_admin(self, bot, chat_id: int, user_id: int) -> bool:
        return user_id in await self.admin_ids(bot, chat_id)
