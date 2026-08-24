"""Link analysis.

The false-positive tests matter as much as the detection ones here: people
share links constantly, and a link checker that flags ordinary URLs makes the
bot unusable in any group where anyone posts an article.
"""
import pytest

from conftest import FakeContext, FakeLLM, FakeMessage, FakeProfiles, FakeUpdate
from models import LinkAnalyzer, Risk
from models.link_analyzer import extract_links
from test_controller import build


def risk_of(text, **kw):
    return LinkAnalyzer(**kw).analyze(text).risk


# --- must NOT fire ---------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "https://github.com/psf/requests is a good library",
        "docs at https://docs.python.org/3/library/re.html",
        "https://binance.com/trade — the real one",
        "https://metamask.io/download",
        "join our group https://t.me/somegroup",
        "t.me/anothergroup",
        "read this www.bbc.co.uk/news article",
        "no links here, just discussing version 1.2.3",
        "the traceback points at file.py line 40",
        "email me at someone@example.com",
        "my metamask wallet broke, any ideas?",
    ],
)
def test_ordinary_messages_are_not_flagged(text):
    assert risk_of(text) is Risk.CLEAN, text


def test_several_normal_links_stay_clean():
    v = LinkAnalyzer().analyze("see https://a.com and https://b.org and https://c.net")
    assert v.risk is Risk.CLEAN


# --- structural deception --------------------------------------------------
@pytest.mark.parametrize(
    "text,expected_fragment",
    [
        ("claim at http://binanace.com/x", "character from 'binance'"),
        ("go https://binance.com@evil.xyz/claim", "credentials-in-url"),
        ("visit https://xn--binnce-mva.com", "punycode"),
        ("login https://binance.security-verify.top", "uses the 'binance' name"),
        ("verify https://metarnask.io/connect", "metamask"),   # rn -> m homoglyph
        ("go https://binancc.com", "binance"),
        ("https://te1egram.org/verify", "telegram"),           # 1 -> l
    ],
)
def test_deceptive_links_are_red_flags(text, expected_fragment):
    v = LinkAnalyzer().analyze(text)
    assert v.risk is Risk.RED_FLAG
    assert expected_fragment in v.reason


@pytest.mark.parametrize(
    "text", ["see bit.ly/3xKfa", "here https://tinyurl.com/abc", "http://cutt.ly/xy"]
)
def test_shorteners_are_only_borderline(text):
    """Hiding the destination is suspicious, not proof — plenty of legitimate
    posts use shorteners."""
    assert risk_of(text) is Risk.FIFTY_FIFTY


def test_raw_ip_links_are_borderline():
    assert risk_of("connect http://51.20.3.4/wallet") is Risk.FIFTY_FIFTY


def test_admin_blocklist_is_honoured():
    assert risk_of("see https://spam.example", blocklist={"spam.example"}) is Risk.RED_FLAG
    assert risk_of("see https://spam.example") is Risk.CLEAN


# --- extraction ------------------------------------------------------------
def test_extraction_dedupes_by_host():
    links = extract_links("https://a.com/1 and https://a.com/2 and https://b.com")
    assert sorted(link.host for link in links) == ["a.com", "b.com"]


def test_extraction_handles_no_scheme():
    assert [link.host for link in extract_links("go to example.com now")] == ["example.com"]


def test_describe_lists_hosts_for_the_model():
    note = LinkAnalyzer().describe("see https://a.com and https://b.org")
    assert "a.com" in note and "b.org" in note


def test_describe_is_empty_without_links():
    assert LinkAnalyzer().describe("just talking") == ""


# --- through the controller ------------------------------------------------
async def test_a_deceptive_link_escalates_even_when_the_model_says_clean(store, bot):
    """A structurally deceptive URL is evidence in its own right — it must not
    depend on the model noticing."""
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles(Risk.RED_FLAG), bot=bot)
    msg = FakeMessage(text="hey everyone, claim yours at http://binanace.com/claim")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert bot.deleted, "the message should not survive"


async def test_an_ordinary_link_does_not_escalate(store, bot):
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles(Risk.RED_FLAG), bot=bot)
    msg = FakeMessage(text="this article explains it https://github.com/psf/requests")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert bot.deleted == [] and bot.sent == []


async def test_link_hosts_are_given_to_the_model(store, bot):
    llm = FakeLLM(Risk.CLEAN)
    controller, _ = build(store, llm, FakeProfiles(), bot=bot)
    msg = FakeMessage(text="check this out https://example.com/page for details")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert "example.com" in llm.calls[0][1]


async def test_a_short_message_that_is_only_a_bad_link_is_still_caught(store, bot):
    """Short-message skipping must not become a hole for bare links."""
    controller, _ = build(store, FakeLLM(Risk.CLEAN), FakeProfiles(Risk.RED_FLAG), bot=bot)
    msg = FakeMessage(text="binanace.com")
    await controller.handle_message(FakeUpdate(msg), FakeContext(bot))
    assert bot.deleted
