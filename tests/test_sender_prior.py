"""The sender prior handed to the model, and why it is coarse.

Two jobs, and the second one is easy to break by accident:

  1. Tell the model roughly who is speaking, so a brand-new account making an
     up-front-payment offer reads differently from a long-standing member.
  2. Be the SAME string for senders in the same situation — because it is part
     of the verdict cache key. An exact message count made every key unique,
     so twenty raid accounts posting one line asked twenty distinct questions
     and paid for twenty answers.

The exact count was never information the model could use: the difference
between "47 prior messages" and "48 prior messages" is noise to it and a cache
miss to us.
"""
import pytest

from models.moderation_model import ModerationModel


class Record:
    def __init__(self, messages_seen=0, strikes=0):
        self.messages_seen = messages_seen
        self.strikes = strikes


def describe(seen, strikes=0, trusted=False):
    model = ModerationModel.__new__(ModerationModel)
    model._links = None
    return ModerationModel._describe(
        model, Record(seen, strikes), trusted, text=""
    )


def test_a_first_message_is_called_out_plainly():
    assert "first message" in describe(0).lower()


def test_neighbouring_message_counts_share_one_prior():
    """The regression: this is what made every cache key unique."""
    assert describe(47) == describe(48)


def test_an_exact_count_is_never_leaked():
    body = describe(47)
    assert "47" not in body


def test_a_newcomer_and_an_old_hand_still_read_differently():
    assert describe(2) != describe(200, trusted=True)


def test_established_membership_is_stated():
    assert "established" in describe(200, trusted=True).lower()


def test_not_yet_established_is_distinguishable():
    body = describe(10, trusted=False).lower()
    assert "established" in body and "not yet" in body


def test_a_clean_record_is_stated_rather_than_implied():
    """Silence about strikes would read as 'unknown', not 'none'."""
    assert "no prior strikes" in describe(30, strikes=0, trusted=True).lower()


def test_one_strike_is_singular():
    body = describe(30, strikes=1)
    assert "1 prior strike." in body
    assert "1 prior strikes" not in body


def test_strike_counts_are_capped_so_they_stop_splitting_the_cache():
    assert describe(30, strikes=7) == describe(30, strikes=9)
    assert "3 or more" in describe(30, strikes=7).lower()


def test_a_repeat_offender_is_still_distinguishable_from_a_clean_record():
    assert describe(30, strikes=7) != describe(30, strikes=0)


def test_twenty_fresh_accounts_produce_one_identical_prior():
    """A raid is many brand-new accounts, so they must collapse to one key."""
    assert len({describe(0) for _ in range(20)}) == 1
