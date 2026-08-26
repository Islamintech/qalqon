"""Keyword filter, file scanner, verdict combination, callback encoding."""
import pytest

from controllers.moderation_controller import MEDIA_FIELDS, attachment_of
from models import FileScanner, KeywordFilter, Risk, Verdict
from views.telegram_view import build_callback, parse_callback


# --- verdict ---------------------------------------------------------------
def test_worst_picks_highest_risk():
    a = Verdict(Risk.CLEAN, "a", "llm")
    b = Verdict(Risk.RED_FLAG, "b", "keyword")
    c = Verdict(Risk.FIFTY_FIFTY, "c", "profile")
    assert Verdict.worst(a, b, c).risk is Risk.RED_FLAG
    assert Verdict.worst(a, c).risk is Risk.FIFTY_FIFTY


def test_worst_keeps_every_signal_as_a_component():
    """Only the winner survives into risk/reason, so without components an
    alert cannot say whether one detector fired or three agreed."""
    llm = Verdict(Risk.RED_FLAG, "scam pitch", "llm")
    kw = Verdict(Risk.CLEAN, "no pattern matched", "keyword")
    link = Verdict(Risk.RED_FLAG, "typosquat", "link")
    combined = Verdict.worst(llm, kw, link)
    assert [c.source for c in combined.components] == ["llm", "keyword", "link"]
    assert combined.reason == "scam pitch"


def test_breakdown_lists_every_signal():
    combined = Verdict.worst(
        Verdict(Risk.RED_FLAG, "scam pitch", "llm"),
        Verdict(Risk.CLEAN, "no pattern matched", "keyword"),
    )
    out = combined.breakdown()
    assert "llm" in out and "keyword" in out
    assert "scam pitch" in out and "no pattern matched" in out


def test_breakdown_marks_a_degraded_signal():
    """A reviewer must be able to see that a detector could not run."""
    combined = Verdict.worst(
        Verdict(Risk.CLEAN, "llm unavailable", "llm", degraded=True),
        Verdict(Risk.FIFTY_FIFTY, "keyword hit", "keyword"),
    )
    assert "CLEAN?" in combined.breakdown()


def test_breakdown_of_a_plain_verdict_is_itself():
    single = Verdict(Risk.RED_FLAG, "dangerous file type .apk", "file")
    assert "file" in single.breakdown() and ".apk" in single.breakdown()


def test_components_do_not_nest_without_limit():
    """profile -> vision -> ... would recurse forever in an alert."""
    inner = Verdict.worst(
        Verdict(Risk.CLEAN, "a", "vision"), Verdict(Risk.CLEAN, "b", "channel")
    )
    outer = Verdict.worst(inner, Verdict(Risk.CLEAN, "c", "keyword"))
    assert all(c.components == () for c in outer.components)


def test_components_are_ignored_for_equality():
    """Verdicts still compare on their substance, not their provenance."""
    plain = Verdict(Risk.RED_FLAG, "x", "llm")
    composed = Verdict.worst(plain, Verdict(Risk.CLEAN, "y", "keyword"))
    assert composed == plain


def test_worst_on_empty_does_not_crash():
    """The old version raised on max() of an empty sequence — which would have
    taken the bot down on any path that gathered no verdicts."""
    assert Verdict.worst().risk is Risk.CLEAN


# --- keywords --------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "hey check out my profile",
        "guaranteed crypto profit here",
        "kuniga 10% foyda kafolatlangan",
        "Гарантированный доход 20% в день",
        "oldindan 300$ to'lang",
        "avval siz pul o'tkazing",
    ],
)
def test_keyword_catches_scam_openers(text):
    hit = KeywordFilter().check(text)
    assert hit is not None and hit.risk is Risk.FIFTY_FIFTY


@pytest.mark.parametrize(
    "text",
    [
        "DM me for details",
        "earn 130000 won a day",
        "is anyone free right now",
        "contact me on telegram",
    ],
)
def test_patterns_that_target_this_community_were_removed(text):
    """These fired before and were wrong here: 'is anyone free' is a shift
    request, a stated wage is a wage, and 'dm me' is how every currency
    exchange in these groups is arranged. Whether such a message is a scam
    depends on whether money is demanded up front — which a regex cannot see,
    so it is left to the model."""
    assert KeywordFilter().check(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "good morning everyone",
        "does anyone know how to fix this bug?",
        "I made a profit on that trade last year",
        "check the docs for the answer",
    ],
)
def test_keyword_leaves_normal_talk_alone(text):
    assert KeywordFilter().check(text) is None


def test_keyword_never_returns_red_flag():
    """Regex matching false-positives easily, so it may raise suspicion but must
    never be enough to act on by itself."""
    kf = KeywordFilter()
    for pattern_text in ("dm me", "free money", "check my profile"):
        hit = kf.check(pattern_text)
        assert hit is None or hit.risk is not Risk.RED_FLAG


# --- files -----------------------------------------------------------------
@pytest.mark.parametrize("name", ["wallet.apk", "setup.exe", "run.bat", "app.jar"])
def test_dangerous_extensions_are_red(name):
    assert FileScanner().scan(name).risk is Risk.RED_FLAG


@pytest.mark.parametrize("name", ["report.pdf", "photo.jpg", "notes.txt", "data.csv"])
def test_ordinary_files_pass(name):
    assert FileScanner().scan(name).risk is Risk.CLEAN


def test_suspicious_name_alone_is_only_fifty_fifty():
    assert FileScanner().scan("free_premium.pdf").risk is Risk.FIFTY_FIFTY


def test_apk_with_mismatched_mime_is_red():
    v = FileScanner().scan("thing.apk", "application/octet-stream")
    assert v.risk is Risk.RED_FLAG
    assert "mismatched mime" in v.reason


@pytest.mark.parametrize("name", ["wallet.apk.txt", "invoice.exe.pdf", "x.scr.jpg"])
def test_a_buried_dangerous_extension_is_a_disguise(name):
    """Hiding .apk behind .txt is deliberate. It will not execute as sent, so
    it is a hint rather than proof — but a real payload is one rename away."""
    v = FileScanner().scan(name)
    assert v.risk is Risk.FIFTY_FIFTY
    assert "double extension" in v.reason


@pytest.mark.parametrize("name", ["archive.tar.gz", "my.notes.txt", "v1.2.report.pdf"])
def test_ordinary_dotted_names_are_not_disguises(name):
    assert FileScanner().scan(name).risk is Risk.CLEAN


def test_the_filename_is_in_the_reason():
    """A reviewer cannot judge "suspicious name term 'wallet'" without knowing
    what the file was actually called."""
    assert "wallet.apk" in FileScanner().scan("wallet.apk").reason


def test_file_without_extension_is_not_punished():
    assert FileScanner().scan("README").risk is Risk.CLEAN


class _Obj:
    def __init__(self, file_name=None, mime_type=None, file_size=None):
        self.file_name = file_name
        self.mime_type = mime_type
        self.file_size = file_size


class _Msg:
    def __init__(self, **kw):
        for attr in MEDIA_FIELDS:
            setattr(self, attr, kw.get(attr))


# Extracting the attachment is Telegram-shaped knowledge, so it lives in the
# controller; the scanner only judges a declared name/type/size. These tests
# cover the pair together, because the bypass they guard against needs both.
def test_a_payload_sent_as_video_is_still_found():
    """The document-only handler let this through."""
    att = attachment_of(_Msg(video=_Obj("wallet.apk", "video/mp4", 1000)))
    assert FileScanner().scan(att.file_name, att.mime_type).risk is Risk.RED_FLAG


def test_nothing_attached_yields_no_attachment():
    assert attachment_of(_Msg()) is None


def test_a_normal_video_is_left_alone():
    att = attachment_of(_Msg(video=_Obj("holiday.mp4", "video/mp4", 1000)))
    assert FileScanner().scan(att.file_name, att.mime_type).risk is Risk.CLEAN


def test_the_first_declared_attachment_wins():
    """A message carries at most one of these in practice; the order must be
    deterministic rather than dict-iteration luck."""
    att = attachment_of(_Msg(document=_Obj("a.pdf", "application/pdf"),
                             video=_Obj("b.mp4", "video/mp4")))
    assert att.file_name == "a.pdf"


# --- callback data ---------------------------------------------------------
def test_callback_roundtrip():
    data = build_callback("ban", -1001234567890, 42)
    assert len(data.encode()) <= 64, "Telegram caps callback_data at 64 bytes"
    assert parse_callback(data) == ("ban", -1001234567890, 42)


@pytest.mark.parametrize("bad", ["", "garbage", "mod|ban", "other|ban|1|2", "mod|ban|x|2"])
def test_callback_rejects_malformed_data(bad):
    assert parse_callback(bad) is None
