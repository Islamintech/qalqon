"""Proof of life.

A dead moderation bot is invisible: the groups look protected, and the failure
generates no alerts precisely because the thing that would alert is the thing
that died. The heartbeat exists so that silence becomes meaningful.
"""
import pytest

from views import Heartbeat
from views.heartbeat import _duration


class Sink:
    def __init__(self):
        self.messages = []

    async def __call__(self, body):
        self.messages.append(body)


class FakeStore:
    def __init__(self, actions=None, fail=False):
        self._actions = actions or {}
        self._fail = fail

    async def stats(self, chat_id=None):
        if self._fail:
            raise RuntimeError("database is unavailable")
        return {"actions": dict(self._actions)}


# --- formatting ------------------------------------------------------------
@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0m"), (90, "1m"), (3700, "1h 1m"), (90000, "1d 1h"), (-5, "0m")],
)
def test_duration_is_readable(seconds, expected):
    assert _duration(seconds) == expected


# --- the messages ----------------------------------------------------------
async def test_startup_is_announced():
    """A restart loop should be visible as a stream of these, not as silence."""
    hb, sink = Heartbeat(FakeStore()), Sink()
    await hb.startup(sink, detail="mode: DRY-RUN")
    assert "started" in sink.messages[0] and "DRY-RUN" in sink.messages[0]


async def test_shutdown_is_announced_so_a_clean_stop_is_distinguishable():
    hb, sink = Heartbeat(FakeStore()), Sink()
    await hb.startup(sink)
    await hb.shutdown(sink)
    assert "stopping" in sink.messages[-1]
    assert "uptime" in sink.messages[-1]


async def test_a_quiet_period_still_sends_a_beat():
    """The whole point: the ABSENCE of this is the alarm, so it cannot be
    conditional on there being something to report."""
    hb, sink = Heartbeat(FakeStore()), Sink()
    await hb.startup(sink)
    sink.messages.clear()
    await hb.beat(sink)
    assert len(sink.messages) == 1
    assert "no moderation actions" in sink.messages[0]


async def test_the_beat_reports_what_happened_since_the_last_one():
    store = FakeStore({"BAN": 2, "DELETE": 5})
    hb, sink = Heartbeat(store), Sink()
    await hb.startup(sink)          # baseline: 2 BAN, 5 DELETE
    store._actions = {"BAN": 3, "DELETE": 9}
    sink.messages.clear()
    await hb.beat(sink)
    body = sink.messages[0]
    assert "1× BAN" in body and "4× DELETE" in body, "deltas, not totals"


async def test_consecutive_beats_do_not_double_count():
    store = FakeStore({"BAN": 1})
    hb, sink = Heartbeat(store), Sink()
    await hb.startup(sink)
    store._actions = {"BAN": 4}
    await hb.beat(sink)
    sink.messages.clear()
    await hb.beat(sink)
    assert "no moderation actions" in sink.messages[0], "the delta must reset"


async def test_a_broken_database_does_not_stop_the_heartbeat():
    """If stats fail we still say we are alive — a missing ping must mean the
    process is gone, not that one query failed."""
    hb, sink = Heartbeat(FakeStore(fail=True)), Sink()
    await hb.startup(sink)
    await hb.beat(sink)
    assert any("still running" in m for m in sink.messages)


async def test_a_failing_send_never_propagates():
    """A moderation bot must not die because a notification failed."""
    async def broken(_body):
        raise RuntimeError("telegram unreachable")

    hb = Heartbeat(FakeStore())
    await hb.startup(broken)     # must not raise
    await hb.shutdown(broken)    # must not raise


async def test_stop_is_safe_when_never_started():
    await Heartbeat(FakeStore()).stop()
