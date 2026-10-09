"""Actions requested from the web dashboard.

The panel is a separate process with a read-only database, and it stays that
way: it never writes moderation state and never calls Telegram. When an admin
presses a button there, the panel ASKS the bot over a private TCP port, and
the bot carries it out through the same Store and View calls its own
commands use — one writer, one place where dry-run is enforced.

Wire format, one exchange per connection, newline-terminated JSON each way:

    -> {"secret": "...", "op": "unban", "chat_id": -100..., "user_id": 42, "by": "ID 7"}
    <- {"ok": true, "note": "unbanned 42"}

The port is never published. The secret is the second lock, for anything
else that can reach the internal network.
"""
import asyncio
import hmac
import json
import logging

from models.store import STATUS_NORMAL

log = logging.getLogger("qalqon.control")

MAX_REQUEST = 4096
READ_TIMEOUT = 5.0


class ControlController:
    def __init__(self, store, view, secret: str) -> None:
        self._store = store
        self._view = view
        self._secret = secret
        self._server: asyncio.base_events.Server | None = None

    # --- the operations --------------------------------------------------
    async def handle(self, request: dict) -> dict:
        supplied = str(request.get("secret", ""))
        if not self._secret or not hmac.compare_digest(supplied, self._secret):
            log.warning("control request REJECTED: bad secret")
            return {"ok": False, "error": "not authorised"}

        op = request.get("op")
        by = str(request.get("by", "dashboard"))[:64]
        try:
            if op == "status":
                return {"ok": True, "dry_run": self._view.dry_run}
            if op == "dry_run":
                value = request.get("value")
                if not isinstance(value, bool):
                    return {"ok": False, "error": "value must be true or false"}
                self._view.set_dry_run(value)
                mode = "DRY-RUN" if value else "⚠️ LIVE — real deletes and bans"
                log.warning("dry_run set to %s from the dashboard by %s", value, by)
                await self._audit(f"⚙️ Mode is now {mode}\nset from the dashboard by {by}")
                return {"ok": True, "dry_run": value, "note": f"mode is now {mode}"}

            chat_id = int(request["chat_id"])
            if op == "leave":
                ok = await self._view.leave_chat(chat_id)
                if ok:
                    await self._audit(f"👋 Left group {chat_id}\nfrom the dashboard by {by}")
                return self._result(ok, f"left group {chat_id}", "could not leave the group")

            user_id = int(request["user_id"])
            if op == "unban":
                ok = await self._view.unban_user(chat_id, user_id)
                await self._store.set_status(chat_id, user_id, STATUS_NORMAL)
                await self._store.clear_strikes(chat_id, user_id)
                await self._audit(
                    f"✅ Unbanned {user_id} in {chat_id}\nfrom the dashboard by {by}"
                )
                return self._result(ok, f"unbanned {user_id}", f"unban failed for {user_id}")
            if op == "forgive":
                await self._store.clear_strikes(chat_id, user_id)
                await self._audit(
                    f"🕊 Strikes cleared for {user_id} in {chat_id}\nfrom the dashboard by {by}"
                )
                return {"ok": True, "note": f"strikes cleared for {user_id}"}
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "chat_id and user_id must be numbers"}
        return {"ok": False, "error": f"unknown operation: {op}"}

    @staticmethod
    def _result(ok: bool, done: str, failed: str) -> dict:
        return {"ok": True, "note": done} if ok else {"ok": False, "error": failed}

    async def _audit(self, text: str) -> None:
        """Every dashboard action lands in the admin chat, so a change made on
        the web is as visible as one made by command."""
        try:
            await self._view.report_to_admins(text)
        except Exception as exc:
            log.warning("could not report dashboard action: %s", exc)

    # --- the socket ------------------------------------------------------
    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), READ_TIMEOUT)
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError
            except ValueError:
                reply = {"ok": False, "error": "bad request"}
            else:
                reply = await self.handle(request)
            writer.write((json.dumps(reply) + "\n").encode())
            await writer.drain()
        except Exception as exc:  # timeouts, oversize lines, dropped peers
            log.warning("control connection failed: %s", exc)
        finally:
            writer.close()

    async def start(self, host: str, port: int) -> None:
        try:
            self._server = await asyncio.start_server(
                self._serve, host, port, limit=MAX_REQUEST
            )
        except OSError as exc:
            # The panel's buttons stop working; moderation must not.
            log.warning("control port %s:%s unavailable, dashboard actions off: %s",
                        host, port, exc)
            return
        log.info("control channel listening on %s:%s", host, port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
