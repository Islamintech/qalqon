# Deploying with Docker (shared host)

Use this instead of the systemd route in `DEPLOY.md` when the box already runs
other services — as ours does (kapply, visa-checker). Two reasons it is the
better fit there:

- **No root needed.** The deploying user is in the `docker` group but has no
  passwordless sudo, so the systemd route would require manual root steps.
- **It matches the host's existing convention** — same `restart: unless-stopped`
  policy, same `~/apps/<project>/` layout. Nobody inheriting the box has to
  learn a second deployment style.

**The bot publishes no ports.** It polls Telegram outbound and listens on
nothing, so on a shared host there is nothing to collide with: no port, no
nginx change, no firewall rule.

## Install

```bash
mkdir -p ~/apps/scamguard && cd ~/apps/scamguard
git clone git@github.com:<owner>/scam-guard.git .
cp .env.example .env && nano .env      # real values
chmod 600 .env
docker compose build
```

Verify before starting anything — inside the container, so it tests the real
runtime rather than your laptop:

```bash
docker compose run --rm --entrypoint python bot scripts/preflight.py <group_id>
```

Then:

```bash
docker compose up -d
docker compose logs -f bot
```

## Two things that will bite you

**Volume ownership.** A bind mount keeps the *host's* ownership, so a container
user the host does not know cannot write to it — the bot crash-loops on
`unable to open database file`. `docker-compose.yml` therefore runs as
`${PUID:-1000}:${PGID:-1000}`. If your user is not uid 1000, put `PUID`/`PGID`
in `.env`. Matching uids also keeps `scamguard.db` readable from the host for
backups, which a root-owned file would not be.

**`DB_PATH` is overridden in compose** to `/data/scamguard.db`. The database
must live on the mounted volume; inside the image a rebuild would erase every
strike, whitelist and ban record.

## Day to day

| | |
|---|---|
| logs | `docker compose logs -f bot` |
| restart | `docker compose restart bot` |
| stop | `docker compose stop bot` |
| update | `git pull && docker compose up -d --build` |
| shell | `docker compose run --rm --entrypoint bash bot` |

## Verifying the supervision

`docker kill` and `docker stop` are recorded as **manual** stops, and
`unless-stopped` deliberately does not restart those — so killing the container
is not a test of crash recovery, it only proves the policy name.

Signalling PID 1 from inside does not work either: the kernel ignores signals
to PID 1 that it has no handler for, within its own PID namespace.

Test it with a disposable container instead — same image, same policy, a command
that exits non-zero:

```bash
docker run -d --restart unless-stopped --name restart-test \
  scamguard:latest python -c "import sys; sys.exit(1)"
sleep 20 && docker inspect -f '{{.RestartCount}}' restart-test   # climbing
docker rm -f restart-test
```

A reboot would also prove it, but **not on a host running other people's
production services** — that is a decision for whoever owns the box, not a
casual check.

## Backups

```cron
0 4 * * * cd /home/<user>/apps/scamguard && sqlite3 data/scamguard.db ".backup 'data/backup-$(date +\%F).db'" && find data -name 'backup-*.db' -mtime +14 -delete
```

`.backup` is safe against a live database; `cp` while the bot writes is not.
