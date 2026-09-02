# Deploying Qalqon on a VPS

Any small Linux box will do — this uses well under 100 MB of RAM and almost no
CPU. The work is all network I/O waiting on Telegram and Groq.

**Python 3.11 or newer.** Debian 12 ships 3.11, Ubuntu 24.04 ships 3.12; both
are fine. Developed and tested on 3.14.

---

## 1. Create a user for it

Never run it as root. A moderation bot handles hostile input by definition.

```bash
sudo adduser --system --group --home /opt/qalqon qalqon
```

## 2. Get the code there

```bash
sudo -u qalqon git clone <your-repo-url> /opt/qalqon
cd /opt/qalqon
```

If the repo is private, use a deploy key or clone locally and `rsync` it up.

## 3. Virtualenv and dependencies

```bash
sudo -u qalqon python3 -m venv /opt/qalqon/.venv
sudo -u qalqon /opt/qalqon/.venv/bin/pip install -r requirements.txt
```

## 4. Credentials

```bash
sudo -u qalqon cp .env.example .env
sudo -u qalqon nano .env          # fill in the real values
sudo chmod 600 /opt/qalqon/.env   # nobody else can read the tokens
```

**Do not copy `qalqon.db` from your dev machine** unless you want your test
strikes in production. Starting empty is correct — everyone begins with a clean
record.

## 5. Verify before starting anything

```bash
sudo -u qalqon /opt/qalqon/.venv/bin/python scripts/preflight.py <group_id>
```

Fix everything it reports. It exits non-zero on any blocker, so this is also
what you would run in CI.

## 6. Install the service

```bash
sudo cp deploy/qalqon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qalqon
```

## 7. Confirm

```bash
systemctl status qalqon          # should be "active (running)"
journalctl -u qalqon -f          # live logs
```

You should also get the `✅ Qalqon started` message in your admin chat.

---

## Verify the supervision actually works

Do not assume it does. **Supervision that silently fails looks exactly like
supervision that works** — and you would only find out during an incident.

```bash
# 1. kill it and confirm it comes back
sudo systemctl kill -s KILL qalqon
sleep 15 && systemctl status qalqon      # active again, restart count +1

# 2. confirm it survives a reboot
sudo reboot
# after it comes up:
systemctl is-enabled qalqon              # "enabled"
systemctl is-active qalqon               # "active"
```

You should get a fresh `✅ Qalqon started` in your admin chat both times.
Seeing a stream of those with no shutdown notices between them means it is
crash-looping — check `journalctl -u qalqon -n 50`.

---

## Day to day

| | |
|---|---|
| logs | `journalctl -u qalqon -f` |
| restart after a config change | `sudo systemctl restart qalqon` |
| stop | `sudo systemctl stop qalqon` |
| is it up? | `systemctl status qalqon` |

**Only one instance may ever poll a token.** Stop the service before running
`main.py` by hand, or the two will fight over the update stream — each seeing a
random half of the messages. The bot detects this (`Conflict`) and exits, which
under `Restart=always` shows up as a restart loop.

## Back up the database

`qalqon.db` holds every strike, whitelist and ban record. It is not
reproducible — losing it means every scammer starts clean and every trusted
member loses their standing.

```bash
sudo crontab -e
```

```cron
0 4 * * * sqlite3 /opt/qalqon/qalqon.db ".backup '/opt/qalqon/backup-$(date +\%F).db'" && find /opt/qalqon -name 'backup-*.db' -mtime +14 -delete
```

`.backup` is safe to run against a live database; copying the file with `cp`
while the bot is writing is not.

## Updating

```bash
cd /opt/qalqon
sudo -u qalqon git pull
sudo -u qalqon .venv/bin/pip install -r requirements.txt
sudo -u qalqon .venv/bin/python -m pytest -q      # requirements-dev.txt
sudo systemctl restart qalqon
```

**If you also run the dashboard, restart it too:**

```bash
sudo -u qalqon .venv/bin/pip install -r requirements-web.txt
sudo systemctl restart qalqon-web
```

`qalqon` and `qalqon-web` are two independent units — that separation is the
point, so the panel can be restarted without interrupting moderation. The cost
is that restarting only `qalqon` leaves the dashboard serving the code it
started with, however long ago that was. A web-only change (anything under
`web/`) shows no sign of having deployed until `qalqon-web` is restarted, and
the symptom is simply the old page, which reads as a browser cache rather than
a missed step.

If a page still looks stale after the restart, hard-reload once (Ctrl+Shift+R)
before assuming the deploy failed — the reverse proxy may be holding it.

The database migrates itself on start; check the logs after a schema change.

Under Docker, `git pull && docker compose up -d --build` rebuilds both — the
code is baked into the image, so a plain `docker compose restart` deploys
nothing.

## What tells you it broke

In order of reliability:

1. **The daily heartbeat stops arriving.** This is the real signal — it catches
   crashes, a dead machine, and a lost network alike. Absence is the alarm.
2. `⏹ Qalqon stopping` with no matching start after it — a clean stop that
   never came back.
3. `systemctl status qalqon` showing `failed` — it cannot start at all,
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
sudo -u qalqon /opt/qalqon/.venv/bin/pip install -r requirements-web.txt
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
sudo cp deploy/qalqon-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qalqon-web
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
