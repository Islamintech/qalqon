"""Conflict: a second instance versus a stale poll.

A real second instance polling the same token must stop the bot — two
moderators on one chat double every ban. But a lone 409 after a network drop
is our own abandoned long poll, and stopping on it cost a restart every time
the network blinked.
"""
from types import SimpleNamespace

import pytest
from telegram.error import Conflict

import main
from main import ConflictGuard


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeApp:
    def __init__(self):
        self.stopped = False

    def stop_running(self):
        self.stopped = True


def context_for(app, err):
    return SimpleNamespace(error=err, application=app)


# --- the guard -------------------------------------------------------------
def test_a_single_conflict_is_tolerated():
    guard = ConflictGuard(threshold=3, window=120, clock=Clock())
    assert guard.record() is False


def test_a_sustained_run_of_conflicts_trips():
    clock = Clock()
    guard = ConflictGuard(threshold=3, window=120, clock=clock)
    assert guard.record() is False
    clock.now = 5
    assert guard.record() is False
    clock.now = 12
    assert guard.record() is True


def test_conflicts_spread_beyond_the_window_never_trip():
    # Oct 7 in production: two stale-poll conflicts an hour apart.
    clock = Clock()
    guard = ConflictGuard(threshold=3, window=120, clock=clock)
    for t in (0, 3600, 7200, 10800):
        clock.now = t
        assert guard.record() is False


def test_old_conflicts_age_out_of_the_window():
    clock = Clock()
    guard = ConflictGuard(threshold=3, window=120, clock=clock)
    guard.record()
    clock.now = 10
    guard.record()
    clock.now = 200  # both earlier ones are now outside the window
    assert guard.record() is False


# --- the error handler -----------------------------------------------------
@pytest.fixture
def fresh_guard(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(main, "_conflicts", ConflictGuard(clock=clock))
    return clock


async def test_one_conflict_does_not_stop_the_bot(fresh_guard):
    app = FakeApp()
    await main.on_error(None, context_for(app, Conflict("terminated by other getUpdates request")))
    assert app.stopped is False


async def test_repeated_conflicts_stop_the_bot(fresh_guard):
    app = FakeApp()
    for t in (0, 2, 4):
        fresh_guard.now = t
        await main.on_error(None, context_for(app, Conflict("terminated by other getUpdates request")))
    assert app.stopped is True
