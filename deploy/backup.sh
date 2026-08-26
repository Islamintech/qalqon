#!/bin/bash
# Nightly snapshot of the moderation database. Every strike, whitelist and ban
# record lives here, and none of it is reproducible.
#
# set -e and the size check below exist because the first version of this
# script exited 0 when the backup had failed — its status came from the `find`
# at the end. A backup that reports success without producing a file is worse
# than no backup, because you stop checking.
set -euo pipefail
cd "$(dirname "$0")"
STAMP=$(date +%F)
OUT="data/backup-$STAMP.db"

# --user: a bind mount keeps the HOST's ownership, so the image's own uid
# cannot write to ./data. Matching the host user is what makes it work.
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/data:/data" qalqon:latest \
  python -c "
import sqlite3
src = sqlite3.connect('file:/data/qalqon.db?mode=ro', uri=True)
dst = sqlite3.connect('/data/backup-$STAMP.db')
src.backup(dst)   # safe against a live database, unlike cp
dst.close(); src.close()
"

# Prove it actually produced something before deleting anything old.
[ -s "$OUT" ] || { echo "BACKUP FAILED: $OUT missing or empty" >&2; exit 1; }
echo "$(date -Is) ok $(stat -c%s "$OUT") bytes -> $OUT"

find "$PWD/data" -name 'backup-*.db' -mtime +14 -delete
