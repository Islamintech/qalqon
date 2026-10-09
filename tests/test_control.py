"""Dashboard actions, carried out by the bot.

The panel never writes the database and never calls Telegram; it asks the bot
over a private port. These pin the three things that keep that safe: nothing
happens without the secret, every action goes through the same View and
Store calls the bot's own commands use, and every action is reported to the
admin chat.
"""
import pytest

from controllers import ControlController
from models.store import STATUS_BANNED, STATUS_NORMAL
from views import TelegramView
from web.control import call

SECRET = "s" * 64
GROUP = -100777


class Bot:
    def __init__(self):
        self.left, self.unbanned, self.sent = [], [], []

    async def leave_chat(self, chat_id):
        self.left.append(chat_id)

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=True):
        self.unbanned.append((chat_id, user_id))

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))


@pytest.fixture
def bot():
    return Bot()


@pytest.fixture
def control(store, bot):
    view = TelegramView(dry_run=True, admin_chat_id="999")
    view.attach(bot)
    return ControlController(store, view, SECRET), view


async def ask(control, **request):
    return await control.handle({"secret": SECRET, "by": "Telegram user 7", **request})


# --- the lock --------------------------------------------------------------
async def test_a_wrong_secret_does_nothing(control, bot):
    ctl, view = control
    reply = await ctl.handle({"secret": "guess", "op": "leave", "chat_id": GROUP})
    assert reply == {"ok": False, "error": "not authorised"}
    assert bot.left == []


async def test_an_empty_configured_secret_refuses_everything(store, bot):
    view = TelegramView(dry_run=True)
    view.attach(bot)
    reply = await ControlController(store, view, "").handle({"secret": "", "op": "status"})
    assert reply["ok"] is False


async def test_unknown_operations_are_refused(control):
    reply = await ask(control[0], op="drop_tables", chat_id=1, user_id=2)
    assert reply["ok"] is False and "unknown" in reply["error"]


async def test_non_numeric_ids_are_refused(control):
    reply = await ask(control[0], op="forgive", chat_id="x", user_id=2)
    assert reply["ok"] is False


# --- the operations --------------------------------------------------------
async def test_status_reports_the_running_mode(control):
    ctl, view = control
    assert await ask(ctl, op="status") == {"ok": True, "dry_run": True}
    view.set_dry_run(False)
    assert (await ask(ctl, op="status"))["dry_run"] is False


async def test_going_live_flips_the_view_and_tells_the_admin_chat(control, bot):
    ctl, view = control
    reply = await ask(ctl, op="dry_run", value=False)
    assert reply["ok"] and view.dry_run is False
    assert any("LIVE" in text and "Telegram user 7" in text for _, text in bot.sent)


async def test_dry_run_only_accepts_a_real_boolean(control):
    ctl, view = control
    reply = await ask(ctl, op="dry_run", value="false")
    assert reply["ok"] is False and view.dry_run is True, "'false' is truthy"


async def test_leave_takes_the_bot_out_even_in_dry_run(control, bot):
    reply = await ask(control[0], op="leave", chat_id=GROUP)
    assert reply["ok"] and bot.left == [GROUP]
    assert any("Left group" in text for _, text in bot.sent)


async def test_unban_clears_the_record_like_the_command_does(control, store):
    await store.set_status(GROUP, 42, STATUS_BANNED)
    reply = await ask(control[0], op="unban", chat_id=GROUP, user_id=42)
    assert reply["ok"]
    rec = await store.get(GROUP, 42)
    assert rec.status == STATUS_NORMAL and rec.strikes == 0


async def test_forgive_clears_strikes(control, store, bot):
    reply = await ask(control[0], op="forgive", chat_id=GROUP, user_id=42)
    assert reply["ok"] and (await store.get(GROUP, 42)).strikes == 0
    assert any("Strikes cleared" in text for _, text in bot.sent)


# --- over the wire ---------------------------------------------------------
async def test_the_panel_client_and_the_bot_server_agree(control):
    ctl, _ = control
    await ctl.start("127.0.0.1", 0)
    port = ctl._server.sockets[0].getsockname()[1]
    try:
        reply = await call("127.0.0.1", port, SECRET, "status")
        assert reply == {"ok": True, "dry_run": True}
        refused = await call("127.0.0.1", port, "wrong", "status")
        assert refused["ok"] is False
    finally:
        await ctl.stop()


async def test_a_stopped_bot_is_an_error_message_not_an_exception(control):
    ctl, _ = control
    await ctl.start("127.0.0.1", 0)
    port = ctl._server.sockets[0].getsockname()[1]
    await ctl.stop()
    reply = await call("127.0.0.1", port, SECRET, "status")
    assert reply["ok"] is False and "not reachable" in reply["error"]
