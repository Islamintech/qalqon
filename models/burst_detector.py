"""Rate signals. Content-blind by design: how FAST someone posts is evidence
independent of what they say, and it is the cheapest raid detector there is —
no model call, no network, just arithmetic.

Two separate things live here:

  FLOOD  one account posting many messages in a few seconds. Classic spam
         delivery, and unlike text analysis it cannot be evaded by rewording.

  RAID   many DIFFERENT new accounts posting in the same short window. A single
         account posting fast is a spammer; fifteen brand-new accounts posting
         at once is a coordinated attack, and the group's alert queue is about
         to be buried.

Deliberately NOT done here: raising anyone's punishment automatically during a
raid. A raid is exactly when false positives are most likely (a lively argument
looks like a burst), and mass-banning real members is far worse than a slow
review queue. Raid state changes how alerts are DELIVERED, not how users are
judged.

All state is in memory: on restart the worst case is that we briefly forget a
burst in progress, which is not worth a database write per message.
"""
import time
from collections import defaultdict, deque

from .verdict import Verdict, Risk


class BurstDetector:
    def __init__(
        self,
        flood_messages: int = 5,
        flood_window: float = 8.0,
        raid_users: int = 5,
        raid_window: float = 60.0,
        raid_cooldown: float = 300.0,
    ) -> None:
        self._flood_n = flood_messages
        self._flood_window = flood_window
        self._raid_n = raid_users
        self._raid_window = raid_window
        self._raid_cooldown = raid_cooldown
        self._user_times: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._chat_joins: dict[int, deque[tuple[float, int]]] = defaultdict(deque)
        self._raid_until: dict[int, float] = {}

    # --- per-user flood --------------------------------------------------
    def record(
        self, chat_id: int, user_id: int, now: float | None = None
    ) -> Verdict:
        """Note a message and report whether this user is flooding."""
        now = time.time() if now is None else now
        times = self._user_times[(chat_id, user_id)]
        times.append(now)
        while times and now - times[0] > self._flood_window:
            times.popleft()

        count = len(times)
        if count >= self._flood_n * 2:
            return Verdict(
                Risk.RED_FLAG,
                f"flooding: {count} messages in {self._flood_window:.0f}s",
                "burst",
            )
        if count >= self._flood_n:
            return Verdict(
                Risk.FIFTY_FIFTY,
                f"posting fast: {count} messages in {self._flood_window:.0f}s",
                "burst",
            )
        return Verdict(Risk.CLEAN, "normal pace", "burst")

    # --- per-chat raid ---------------------------------------------------
    def note_new_account(
        self, chat_id: int, user_id: int, now: float | None = None
    ) -> bool:
        """Record activity from an account with no history here. Returns True
        when this tips the chat into raid state."""
        now = time.time() if now is None else now
        seen = self._chat_joins[chat_id]
        seen.append((now, user_id))
        while seen and now - seen[0][0] > self._raid_window:
            seen.popleft()

        distinct = {uid for _, uid in seen}
        if len(distinct) >= self._raid_n:
            was_raiding = self.raid_active(chat_id, now)
            self._raid_until[chat_id] = now + self._raid_cooldown
            return not was_raiding  # True only on the transition into a raid
        return False

    def raid_active(self, chat_id: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self._raid_until.get(chat_id, 0.0) > now

    def raid_size(self, chat_id: int) -> int:
        return len({uid for _, uid in self._chat_joins.get(chat_id, ())})

    # --- housekeeping ----------------------------------------------------
    def prune(self, now: float | None = None) -> None:
        """Drop tracking for users who have gone quiet, so a long-running bot
        does not accumulate an entry per user who ever spoke."""
        now = time.time() if now is None else now
        for key, times in list(self._user_times.items()):
            while times and now - times[0] > self._flood_window:
                times.popleft()
            if not times:
                del self._user_times[key]
        for chat_id, seen in list(self._chat_joins.items()):
            while seen and now - seen[0][0] > self._raid_window:
                seen.popleft()
            if not seen:
                del self._chat_joins[chat_id]
