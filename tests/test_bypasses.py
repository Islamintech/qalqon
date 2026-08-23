"""Regression tests for three ways a scammer could previously get through.

Each of these was a real hole, so each test states the bypass it closes.
"""
import pytest

from conftest import FakeContext, FakeLLM, FakeMessage, FakeProfiles, FakeUpdate
from models import Risk
from test_controller import build, _Doc


# --- 1. edited messages ----------------------------------------------------
async def send_edit(controller, bot, text, chat_id=-1001):
    msg = FakeMessage(text=text, chat_id=chat_id)
    await controller.handle_message(
        FakeUpdate(msg, chat_id=chat_id, edited=True), FakeContext(bot)
    )
    return msg


async def test_an_edited_message_is_moderated(store, bot):
    """THE BYPASS: post "hi", let it clear, then edit in the scam pitch. The bot
    was not even subscribed to edit updates."""
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.RED_FLAG))
    await send_edit(controller, bot, "actually, invest with me, guaranteed returns")
    assert bot.deleted and bot.banned == [(-1001, 100)]


async def test_an_edit_does_not_inflate_the_message_count(store, bot):
    """Otherwise editing one message repeatedly would farm tenure toward the
    trust threshold."""
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles())
    for _ in range(5):
        await send_edit(controller, bot, "a perfectly ordinary message")
    assert (await store.get(-1001, 100)).messages_seen == 0


async def test_a_clean_edit_is_still_free(store, bot):
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles())
    await send_edit(controller, bot, "fixing my typo in this sentence")
    assert bot.deleted == [] and bot.sent == []


# --- 2. captions -----------------------------------------------------------
async def send_caption(controller, bot, caption, **media):
    msg = FakeMessage(text=None, caption=caption, **media)
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    return msg


async def test_a_scam_caption_on_a_clean_photo_is_caught(store, bot):
    """THE BYPASS: filters.TEXT does not match captions, so the words were never
    read — the photo went to the file handler, which judged only the .jpg."""
    llm = FakeLLM(Risk.RED_FLAG)
    controller, _ = build(store, llm, FakeProfiles(Risk.RED_FLAG))
    await send_caption(controller, bot, "guaranteed 300% returns, dm me now")
    assert llm.calls, "the caption must reach the model"
    assert bot.banned == [(-1001, 100)]


async def test_the_alert_says_the_text_came_from_a_caption(store, bot):
    """A caption and a plain message read identically in an alert otherwise, so
    a reviewer cannot tell which path caught it."""
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.RED_FLAG))
    await send_caption(controller, bot, "guaranteed 300% returns, dm me now")
    assert "caption:" in bot.sent[0][1]


async def test_the_alert_says_text_for_a_plain_message(store, bot):
    controller, _ = build(store, FakeLLM(Risk.RED_FLAG), FakeProfiles(Risk.RED_FLAG))
    msg = FakeMessage(text="guaranteed 300% returns, dm me now")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert "text:" in bot.sent[0][1]


async def test_a_clean_caption_is_left_alone(store, bot):
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles())
    await send_caption(controller, bot, "my dog at the beach last weekend")
    assert bot.deleted == [] and bot.sent == []


async def test_caption_and_payload_are_both_judged(store, bot):
    """A captioned .apk must not be judged on only one of its two signals —
    which is exactly what two competing handlers would have done."""
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles(Risk.CLEAN))
    await send_caption(
        controller, bot, "here is the free wallet app",
        document=_Doc("wallet.apk", "application/octet-stream"),
    )
    assert bot.deleted, "the dangerous file must still be caught"


async def test_message_with_neither_text_nor_file_is_ignored(store, bot):
    llm = FakeLLM(Risk.RED_FLAG)
    controller, _ = build(store, llm, FakeProfiles())
    msg = FakeMessage(text=None, caption=None)
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert llm.calls == [] and bot.sent == []


# --- 3. failing open under load -------------------------------------------
class DeadLLM:
    """A model that cannot be reached — what a rate-limited raid looks like."""

    def __init__(self):
        self.calls = []

    async def analyze(self, text, context=""):
        from models import Verdict

        self.calls.append((text, context))
        return Verdict(Risk.CLEAN, "llm unavailable: 429", "llm", degraded=True)


async def test_an_outage_does_not_auto_punish_anyone(store, bot):
    """Fail SAFE on the action: our own outage must never ban a user."""
    controller, _ = build(store, DeadLLM(), FakeProfiles(Risk.RED_FLAG))
    await send_edit(controller, bot, "some perfectly ordinary sentence here")
    assert bot.banned == [] and bot.deleted == []


async def test_an_outage_is_reported_to_admins(store, bot):
    """...but NOT silently. The old code turned every failure into a CLEAN and
    an outage looked exactly like a quiet day."""
    controller, _ = build(store, DeadLLM(), FakeProfiles())
    await send_edit(controller, bot, "some perfectly ordinary sentence here")
    assert bot.sent, "an outage must be visible"
    assert "DEGRADED" in bot.sent[0][1]


async def test_the_outage_warning_does_not_flood_the_queue(store, bot):
    """One notice per cooldown, not one per message — otherwise a multi-hour
    outage buries the review queue under identical alerts."""
    controller, _ = build(store, DeadLLM(), FakeProfiles())
    for i in range(25):
        await send_edit(controller, bot, f"ordinary message number {i} here")
    assert len(bot.sent) == 1


async def test_keyword_moderation_survives_an_outage(store, bot):
    """Degraded is not disabled: the regex pass still works, so blatant scams
    are still caught while the model is down."""
    controller, _ = build(store, DeadLLM(), FakeProfiles(Risk.RED_FLAG))
    msg = FakeMessage(text="check out my profile for guaranteed profits")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert bot.deleted, "keyword hits must still be actioned during an outage"
    alerts = [t for _, t, _ in bot.sent if "Deleted" in t]
    assert alerts, "and the action must still reach the admins"
    assert "DEGRADED" in alerts[0], "and the alert must say detection is impaired"
