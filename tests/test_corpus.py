"""The community's own messages must survive moderation.

These groups are Uzbek workers in South Korea, and their two most common
messages — daily work announcements and won/so'm currency exchange — look like
textbook scams to a naive filter. Before this corpus existed, four of fifteen
legitimate messages were flagged and TWO of them were banned outright.

Only the deterministic half is tested here: no legitimate message may trip a
keyword pattern or the link analyser. The model's own judgement is measured by
scripts/evaluate.py, which costs API calls and is not perfectly deterministic,
so it does not belong in a suite that runs on every change.
"""
import pytest

from corpus import LEGITIMATE, SCAMS
from models import KeywordFilter, LinkAnalyzer, Risk


@pytest.mark.parametrize("text", LEGITIMATE)
def test_no_legitimate_message_trips_a_keyword(text):
    """A shift request is not a lonely stranger; a stated wage is not an
    earnings promise; 'write to me' is how every exchange is arranged."""
    hit = KeywordFilter().check(text)
    assert hit is None, f"false positive: {hit.reason if hit else ''}"


@pytest.mark.parametrize("text", LEGITIMATE)
def test_no_legitimate_message_trips_the_link_checker(text):
    assert LinkAnalyzer().analyze(text).risk is Risk.CLEAN


def test_the_patterns_still_catch_blatant_scams():
    """Removing the over-broad patterns must not have removed the useful ones.
    The rest are the model's job — this only guards the cheap first pass."""
    kf = KeywordFilter()
    caught = [t for t in SCAMS if kf.check(t)]
    assert len(caught) >= 6, (
        f"only {len(caught)}/{len(SCAMS)} caught by keywords alone"
    )


@pytest.mark.parametrize("text", [
    "Mening profilimni ko'ring, sizga yoqadi",
    "Mening profilimni ko‘ring",       # different apostrophe
    "mening profilimni koring",         # no apostrophe at all
])
def test_uzbek_profile_bait_is_caught_however_it_is_typed(text):
    """Uzbek is written with several apostrophes and often none; matching one
    shape would miss most real messages."""
    assert KeywordFilter().check(text) is not None
