"""The escalation matrix. This is the safety-critical surface: a wrong cell
here either bans an innocent member or lets a scammer stay."""
import pytest

from models import Action, Policy, Risk, Verdict, file_decision


def v(risk, source="llm"):
    return Verdict(risk, "because", source)


C, F, R = Risk.CLEAN, Risk.FIFTY_FIFTY, Risk.RED_FLAG


@pytest.mark.parametrize(
    "content,profile,expected",
    [
        (C, C, Action.NONE),
        (C, R, Action.NONE),          # a bad profile alone is not an offence
        (F, C, Action.REVIEW),
        (F, F, Action.REVIEW),
        (F, R, Action.DELETE),
        (R, C, Action.DELETE),        # lone red flag -> remove, don't ban
        (R, F, Action.BAN),
        (R, R, Action.BAN),
    ],
)
def test_base_matrix(content, profile, expected):
    """The matrix itself, with the first-offence cap out of the way — that cap
    is a separate adjustment on top and has its own tests below."""
    p = Policy(require_history_to_ban=False)
    assert p.decide(v(content), v(profile)).action is expected


def test_clean_content_never_acts_whatever_the_history():
    d = Policy().decide(v(C), v(R), strikes=99, trusted=False)
    assert d.action is Action.NONE


def test_strikes_escalate_one_step_per_threshold():
    p = Policy(strikes_to_escalate=2)
    # FIFTY_FIFTY + clean profile is normally just a REVIEW...
    assert p.decide(v(F), v(C), strikes=0).action is Action.REVIEW
    assert p.decide(v(F), v(C), strikes=1).action is Action.REVIEW
    assert p.decide(v(F), v(C), strikes=2).action is Action.DELETE
    assert p.decide(v(F), v(C), strikes=4).action is Action.BAN
    # ...and it can't escalate past BAN.
    assert p.decide(v(F), v(C), strikes=400).action is Action.BAN


def test_trusted_member_is_capped_at_review():
    p = Policy()
    assert p.decide(v(R), v(R), trusted=False).action is Action.BAN
    assert p.decide(v(R), v(R), trusted=True).action is Action.REVIEW


def test_trust_cap_beats_strike_escalation():
    """Order matters: if strikes were applied after the cap, a trusted member
    with old strikes could still be auto-banned."""
    p = Policy(strikes_to_escalate=1)
    assert p.decide(v(F), v(C), strikes=10, trusted=True).action is Action.REVIEW


def test_review_alone_earns_no_strike():
    """Otherwise borderline messages would snowball into a ban on their own."""
    assert Policy().decide(v(F), v(C)).add_strike is False
    assert Policy().decide(v(R), v(C)).add_strike is True
    assert Policy().decide(v(R), v(R)).add_strike is True


def test_missing_profile_is_treated_as_clean_not_as_guilt():
    d = Policy().decide(v(R), profile=None)
    assert d.action is Action.DELETE


def test_profile_confirmation_disabled():
    """Judging on content alone. The first-offence cap still applies, and here
    it matters MORE, not less: with the profile ignored there is only ever one
    signal, so nothing can corroborate it. A first offence is removed, a second
    is banned."""
    p = Policy(require_profile_confirmation=False)
    assert p.decide(v(R), v(C)).action is Action.DELETE
    assert p.decide(v(R), v(C), strikes=1).action is Action.BAN
    assert p.decide(v(F), v(C)).action is Action.REVIEW
    # ...and an operator who wants the old behaviour can still have it.
    old = Policy(require_profile_confirmation=False, require_history_to_ban=False)
    assert old.decide(v(R), v(C)).action is Action.BAN


@pytest.mark.parametrize(
    "risk,strikes,expected",
    [
        (C, 0, Action.NONE),
        (F, 0, Action.REVIEW),
        (R, 0, Action.DELETE),
        (R, 1, Action.BAN),    # second dangerous file is not an accident
    ],
)
def test_file_decision(risk, strikes, expected):
    assert file_decision(v(risk, "file"), strikes).action is expected


# --- a first offence must not end in a ban ----------------------------------
def test_a_newcomer_is_not_banned_on_one_red_flag_and_a_missing_avatar():
    """The exact case seen in production: the model calls the message
    RED_FLAG, the profile scores FIFTY_FIFTY for nothing but "no profile
    photo", and the matrix bans. That is one detector plus a missing avatar,
    against a member with no history and no invite link back."""
    d = Policy().decide(
        Verdict(Risk.RED_FLAG, "upfront money demand", "llm"),
        Verdict(Risk.FIFTY_FIFTY, "no profile photo", "photo"),
        strikes=0, trusted=False,
    )
    assert d.action is Action.DELETE
    assert "first offence" in d.reason


def test_both_detectors_red_still_bans_a_newcomer():
    """The cap asks for corroboration, not for patience. Two independent
    signals agreeing is corroboration, so it is not weakened."""
    d = Policy().decide(
        Verdict(Risk.RED_FLAG, "advance-fee pitch", "llm"),
        Verdict(Risk.RED_FLAG, "scam bio and linked channel", "profile"),
        strikes=0, trusted=False,
    )
    assert d.action is Action.BAN


def test_a_prior_strike_restores_the_ban():
    """A repeat offender has the history the first-offence cap asks for, so
    the second attempt is treated exactly as before."""
    d = Policy().decide(
        Verdict(Risk.RED_FLAG, "upfront money demand", "llm"),
        Verdict(Risk.FIFTY_FIFTY, "no profile photo", "photo"),
        strikes=1, trusted=False,
    )
    assert d.action is Action.BAN


def test_the_cap_still_takes_the_strike():
    """Downgrading the action must not also forgive it — without the strike,
    a scammer could repeat the same message forever and never escalate."""
    d = Policy().decide(
        Verdict(Risk.RED_FLAG, "upfront money demand", "llm"),
        Verdict(Risk.FIFTY_FIFTY, "no profile photo", "photo"),
        strikes=0, trusted=False,
    )
    assert d.add_strike is True


def test_ban_on_first_offence_can_be_restored():
    """The old behaviour stays available for an operator who wants it."""
    d = Policy(require_history_to_ban=False).decide(
        Verdict(Risk.RED_FLAG, "upfront money demand", "llm"),
        Verdict(Risk.FIFTY_FIFTY, "no profile photo", "photo"),
        strikes=0, trusted=False,
    )
    assert d.action is Action.BAN
