"""The panel's only way to change anything: ask the bot.

See controllers/control_controller.py for why the panel does not act itself.
Every failure comes back as {"ok": False, "error": ...} rather than raising,
so a stopped bot shows up as a message on the page, not a 500.
"""
import asyncio
import json

CONNECT_TIMEOUT = 3.0
REPLY_TIMEOUT = 15.0


async def call(host: str, port: int, secret: str, op: str, **fields) -> dict:
    request = {"secret": secret, "op": op, **fields}
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError) as exc:
        return {"ok": False, "error": f"the bot is not reachable ({exc or 'timeout'})"}
    try:
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), REPLY_TIMEOUT)
        reply = json.loads(line) if line else None
        if not isinstance(reply, dict):
            return {"ok": False, "error": "the bot gave no answer"}
        return reply
    except (OSError, asyncio.TimeoutError, ValueError) as exc:
        return {"ok": False, "error": f"the bot did not answer ({exc or 'timeout'})"}
    finally:
        writer.close()
