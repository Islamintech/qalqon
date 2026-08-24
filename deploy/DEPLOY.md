# Deploying ScamGuard on a VPS

Any small Linux box will do — this uses well under 100 MB of RAM and almost no
CPU. The work is all network I/O waiting on Telegram and Groq.

**Python 3.11 or newer.** Debian 12 ships 3.11, Ubuntu 24.04 ships 3.12; both
are fine. Developed and tested on 3.14.

---

## 1. Create a user for it

Never run it as root. A moderation bot handles hostile input by definition.

```bash
sudo adduser --system --group --home /opt/scamguard scamguard
```

## 2. Get the code there

```bash
sudo -u scamguard git clone <your-repo-url> /opt/scamguard
cd /opt/scamguard
```

If the repo is private, use a deploy key or clone locally and `rsync` it up.

## 3. Virtualenv and dependencies

```bash
sudo -u scamguard python3 -m venv /opt/scamguard/.venv
sudo -u scamguard /opt/scamguard/.venv/bin/pip install -r requirements.txt
```

## 4. Credentials

```bash
sudo -u scamguard cp .env.example .env
sudo -u scamguard nano .env          # fill in the real values
sudo chmod 600 /opt/scamguard/.env   # nobody else can read the tokens
```

**Do not copy `scamguard.db` from your dev machine** unless you want your test
strikes in production. Starting empty is correct — everyone begins with a clean
record.

## 5. Verify before starting anything

```bash
sudo -u scamguard /opt/scamguard/.venv/bin/python scripts/preflight.py <group_id>
```

Fix everything it reports. It exits non-zero on any blocker, so this is also
what you would run in CI.

## 6. Install the service

```bash
sudo cp deploy/scamguard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scamguard
```

## 7. Confirm

```bash
systemctl status scamguard          # should be "active (running)"
journalctl -u scamguard -f          # live logs
```

You should also get the `✅ ScamGuard started` message in your admin chat.

---

## Verify the supervision actually works

Do not assume it does. **Supervision that silently fails looks exactly like
supervision that works** — and you would only find out during an incident.

```bash
# 1. kill it and confirm it comes back
sudo systemctl kill -s KILL scamguard
sleep 15 && systemctl status scamguard      # active again, restart count +1

# 2. confirm it survives a reboot
sudo reboot
# after it comes up:
systemctl is-enabled scamguard              # "enabled"
systemctl is-active scamguard               # "active"
```

You should get a fresh `✅ ScamGuard started` in your admin chat both times.
Seeing a stream of those with no shutdown notices between them means it is
crash-looping — check `journalctl -u scamguard -n 50`.

---

## Day to day

| | |
|---|---|
| logs | `journalctl -u scamguard -f` |
| restart after a config change | `sudo systemctl restart scamguard` |
| stop | `sudo systemctl stop scamguard` |
| is it up? | `systemctl status scamguard` |

**Only one instance may ever poll a token.** Stop the service before running
`main.py` by hand, or the two will fight over the update stream — each seeing a
random half of the messages. The bot detects this (`Conflict`) and exits, which
under `Restart=always` shows up as a restart loop.

## Back up the database

`scamguard.db` holds every strike, whitelist and ban record. It is not
reproducible — losing it means every scammer starts clean and every trusted
member loses their standing.

```bash
sudo crontab -e
```

```cron
0 4 * * * sqlite3 /opt/scamguard/scamguard.db ".backup '/opt/scamguard/backup-$(date +\%F).db'" && find /opt/scamguard -name 'backup-*.db' -mtime +14 -delete
```

`.backup` is safe to run against a live database; copying the file with `cp`
while the bot is writing is not.

## Updating

```bash
cd /opt/scamguard
sudo -u scamguard git pull
sudo -u scamguard .venv/bin/pip install -r requirements.txt
sudo -u scamguard .venv/bin/python -m pytest -q      # requirements-dev.txt
sudo systemctl restart scamguard
```

The database migrates itself on start; check the logs after a schema change.

## What tells you it broke

In order of reliability:

1. **The daily heartbeat stops arriving.** This is the real signal — it catches
   crashes, a dead machine, and a lost network alike. Absence is the alarm.
2. `⏹ ScamGuard stopping` with no matching start after it — a clean stop that
   never came back.
3. `systemctl status scamguard` showing `failed` — it cannot start at all,
   usually a config error after an edit.

If you want a machine to watch it instead of you, point the heartbeat at a free
uptime monitor (healthchecks.io and similar) — that also detects the VPS itself
going away, which nothing running *on* the VPS can.

---

# The dashboard (optional)

A read-only web panel: statistics, per-group breakdown, recent decisions, and
how often a human overturned the bot.

It runs as a **separate process** that opens the database **read-only**, so a
bug or compromise in the web layer cannot corrupt moderation state, and the
panel can crash without interrupting moderation.

**It renders real users' message text.** That is necessary for judging whether
a flag was a false positive, but it makes the panel as sensitive as the groups
it watches. HTTPS and a tight allow-list are not optional.

## 1. Extra dependencies

```bash
sudo -u scamguard /opt/scamguard/.venv/bin/pip install -r requirements-web.txt
```

## 2. Tell BotFather the domain

The Telegram login widget refuses to load on a domain the bot does not claim:

```
/setdomain  ->  your bot  ->  panel.example.com
```

## 3. Configure

In `.env`:

```
WEB_ADMIN_IDS=1395418600          # comma-separated Telegram user ids
WEB_BOT_USERNAME=you_are_safebot  # no @
WEB_BASE_URL=https://panel.example.com
WEB_SESSION_SECRET=               # empty derives one from the bot token
```

**`WEB_ADMIN_IDS` empty denies everyone.** That is deliberate: defaulting to
open would mean a forgotten value silently publishes every moderation record.

## 4. Service + HTTPS

```bash
sudo cp deploy/scamguard-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scamguard-web
```

It binds to `127.0.0.1:8080` only. Put a reverse proxy in front for TLS —
Caddy does certificates automatically:

```
# /etc/caddy/Caddyfile
panel.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

```bash
sudo apt install caddy && sudo systemctl reload caddy
```

Do **not** expose port 8080 directly. Without TLS the session cookie and every
message shown travel in clear text.

## 5. Check it

```bash
curl -s localhost:8080/healthz          # {"ok":true}
```

Then open `https://panel.example.com`, sign in with Telegram, and confirm you
land on the dashboard. Signing in with a non-allow-listed account should be
refused — worth testing once, because that check is the only thing between the
internet and your groups' private messages.
