"""The dashboard's buttons.

They must only work for a signed-in admin, only from the dashboard itself,
and only by asking the bot — the panel itself still changes nothing.
"""
from fastapi.testclient import TestClient

from web import app as web_app
from web.auth import issue_session

ORIGIN = {"origin": "http://testserver"}


def client(signed_in=True):
    c = TestClient(web_app.app)
    if signed_in:
        c.cookies.set(web_app.COOKIE, issue_session(7, web_app.SECRET))
    return c


# --- who may press them ----------------------------------------------------
def test_signed_out_actions_go_to_the_login(bot_control):
    with client(signed_in=False) as c:
        r = c.post("/manage/leave", data={"chat": "-100"}, headers=ORIGIN,
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert [op for op, _ in bot_control.calls] == []


def test_a_cross_site_post_is_refused(bot_control):
    with client() as c:
        r = c.post("/manage/unban", data={"chat": "-100", "user": "42"},
                   headers={"origin": "https://evil.example"})
    assert "did not come from the dashboard" in r.text
    assert "unban" not in [op for op, _ in bot_control.calls]


def test_a_post_with_no_origin_at_all_is_refused(bot_control):
    with client() as c:
        r = c.post("/manage/forgive", data={"chat": "-100", "user": "42"})
    assert "did not come from the dashboard" in r.text


# --- what they do ----------------------------------------------------------
def test_unban_asks_the_bot_with_who_pressed_it(bot_control):
    with client() as c:
        r = c.post("/manage/unban", data={"chat": "-100", "user": "42"}, headers=ORIGIN)
    assert r.status_code == 200 and "Done" in r.text
    assert ("unban", {"chat_id": -100, "user_id": 42, "by": "Telegram user 7"}) in bot_control.calls


def test_leave_asks_the_bot(bot_control):
    with client() as c:
        c.post("/manage/leave", data={"chat": "-100555"}, headers=ORIGIN)
    assert ("leave", {"chat_id": -100555, "by": "Telegram user 7"}) in bot_control.calls


def test_leave_shows_a_confirmation_first(bot_control):
    with client() as c:
        r = c.get("/manage/leave?chat=-100555")
    assert "Remove bot" in r.text and 'action="/manage/leave"' in r.text
    assert "leave" not in [op for op, _ in bot_control.calls], "a GET must change nothing"


def test_going_live_needs_a_confirmation_page(bot_control):
    with client() as c:
        page = c.get("/manage/mode").text
        assert "Go live" in page
        c.post("/manage/mode", data={"dry_run": "off"}, headers=ORIGIN)
    assert ("dry_run", {"value": False, "by": "Telegram user 7"}) in bot_control.calls


def test_a_failure_from_the_bot_is_shown_not_hidden(bot_control):
    bot_control.replies["leave"] = {"ok": False, "error": "could not leave the group"}
    with client() as c:
        r = c.post("/manage/leave", data={"chat": "-100"}, headers=ORIGIN)
    assert "Not done" in r.text and "could not leave the group" in r.text


# --- the mode badge --------------------------------------------------------
def test_the_badge_shows_what_the_running_bot_says(bot_control):
    bot_control.replies["status"] = {"ok": True, "dry_run": False}
    with client() as c:
        body = c.get("/app").text
    assert 'class="pill live"' in body


def test_the_badge_says_so_when_the_bot_does_not_answer(bot_control):
    bot_control.replies["status"] = {"ok": False, "error": "not reachable"}
    with client() as c:
        body = c.get("/app").text
    assert "Bot offline" in body
