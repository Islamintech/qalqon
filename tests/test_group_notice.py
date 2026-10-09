"""The note left in the group after a removal.

Members who saw a message vanish, or a person disappear, deserve to know it
was the bot and why. But the note must be true (only for what really
happened), must not advertise the scammer, and must not linger or flood.
"""
import asyncio
from types import SimpleNamespace

import pytest

from models.events import MessageJudged
from models.verdict import Action, Risk, Verdict
from views import TelegramView
from views.telegram_view import NOTICE_GAP, group_notice

GROUP = -100123


class Bot:
    def __init__(self, fail_delete=False):
        self.sent, self.deleted, self.banned = [], [], []
        self._next_id = 500
        self._fail_delete = fail_delete

    async def send_message(self, chat_id, text, reply_markup=None):
        self._next_id += 1
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=self._next_id)

    async def delete_message(self, chat_id, message_id):
        if self._fail_delete and message_id < 500:
            raise RuntimeError("message to delete not found")
        self.deleted.append((chat_id, message_id))

    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def judged(action, source="link", username="crypto_profit_xx", message_id=7):
    return MessageJudged(
        chat_id=GROUP, chat_title="t", message_id=message_id, user_id=42,
        username=username, action=action, reason="matched t.me/scam invite",
        content=Verdict(Risk.RED_FLAG, "matched t.me/scam invite", source),
        profile=None, text="earn $500 a day",
    )


def make(bot, dry_run=False, ttl=60, clock=None):
    view = TelegramView(dry_run=dry_run, notice_ttl=ttl, clock=clock or Clock())
    view.attach(bot)
    return view


def group_messages(bot):
    return [text for chat, text in bot.sent if chat == GROUP]


# --- wording ---------------------------------------------------------------
def test_a_delete_notice_gives_the_reason_in_uzbek_and_english():
    text = group_notice(Action.DELETE, "link")
    assert "Xabar o'chirildi" in text and "Sabab: shubhali havola" in text
    assert "A message was removed" in text and "Reason: suspicious link" in text


def test_a_ban_notice_says_the_user_was_removed():
    text = group_notice(Action.BAN, "file")
    assert "guruhdan chiqarildi" in text and "removed from the group" in text
    assert "dangerous file" in text


def test_an_unknown_signal_still_gets_a_generic_reason():
    assert "suspicious message" in group_notice(Action.DELETE, "photo")


async def test_the_notice_never_names_the_scammer_or_the_detector_reason():
    bot = Bot()
    await make(bot).on_event(judged(Action.DELETE))
    [text] = group_messages(bot)
    assert "crypto_profit_xx" not in text, "the handle is often the advert"
    assert "t.me/scam" not in text, "the detector's reason is a how-to"


# --- only for what really happened ----------------------------------------
async def test_a_real_delete_posts_one_notice():
    bot = Bot()
    await make(bot).on_event(judged(Action.DELETE))
    assert len(group_messages(bot)) == 1


async def test_a_ban_posts_the_ban_notice():
    bot = Bot()
    await make(bot).on_event(judged(Action.BAN))
    [text] = group_messages(bot)
    assert "removed from the group" in text


async def test_dry_run_posts_nothing_in_the_group():
    bot = Bot()
    await make(bot, dry_run=True).on_event(judged(Action.DELETE))
    assert group_messages(bot) == []


async def test_review_posts_nothing_because_nothing_was_removed():
    bot = Bot()
    await make(bot).on_event(judged(Action.REVIEW))
    assert group_messages(bot) == []


async def test_a_failed_delete_posts_nothing():
    bot = Bot(fail_delete=True)
    await make(bot).on_event(judged(Action.DELETE))
    assert group_messages(bot) == []


async def test_ttl_zero_turns_notices_off():
    bot = Bot()
    await make(bot, ttl=0).on_event(judged(Action.DELETE))
    assert group_messages(bot) == []


# --- tidy, and never a flood ----------------------------------------------
async def test_the_notice_removes_itself_after_the_ttl():
    bot = Bot()
    await make(bot, ttl=0.01).on_event(judged(Action.DELETE))
    await asyncio.sleep(0.05)
    notice_id = 501
    assert (GROUP, notice_id) in bot.deleted


async def test_a_raid_gets_one_notice_per_gap_not_one_per_removal():
    bot, clock = Bot(), Clock()
    view = make(bot, clock=clock)
    for i in range(5):
        await view.on_event(judged(Action.DELETE, message_id=i))
    assert len(group_messages(bot)) == 1
    clock.now += NOTICE_GAP
    await view.on_event(judged(Action.DELETE, message_id=9))
    assert len(group_messages(bot)) == 2


async def test_shutdown_removes_notices_still_waiting():
    bot = Bot()
    view = make(bot, ttl=3600)
    await view.on_event(judged(Action.DELETE))
    await view.clear_notices()
    assert (GROUP, 501) in bot.deleted
