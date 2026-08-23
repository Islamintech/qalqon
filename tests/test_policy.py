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
    assert Policy().decide(v(content), v(profile)).action is expected


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
    p = Policy(require_profile_confirmation=False)
    assert p.decide(v(R), v(C)).action is Action.BAN
    assert p.decide(v(F), v(C)).action is Action.REVIEW


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
