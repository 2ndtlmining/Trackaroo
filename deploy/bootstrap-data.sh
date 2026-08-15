#!/bin/sh
# Trackaroo bootstrap: hydrate a fresh DB with the JSON snapshots baked into
# the image (at /app/seed-data) so the dashboard isn't empty on first boot.
#
# On a brand-new volume the DB is created empty by seed.py, so we ingest the
# historical data/*.json shipped with the image. If the DB already has
# snapshots (existing volume), this is a no-op. Idempotent: a re-run on a
# partially hydrated DB skips duplicate snapshot dates (ingest.py).

set -e
[ -d /app/seed-data ] || exit 0

log() {
    echo "[trackaroo] $(date '+%Y-%m-%d %H:%M:%S') $1"
}

# Only hydrate if the DB has no snapshots yet.
has_snapshots=$(python - <<'PY'
import sqlite3
import os
from pathlib import Path
db = Path(os.environ.get("TRACKAROO_DB", "/data/trackaroo.db"))
if not db.exists():
    print(0)
else:
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
        print(n)
    except sqlite3.OperationalError:
        print(0)
    finally:
        conn.close()
PY
)

if [ "$has_snapshots" -gt 0 ]; then
    log "DB already has ${has_snapshots} snapshots — skipping bootstrap hydrate."
    exit 0
fi

seed_files=$(find /app/seed-data -maxdepth 1 -name '*.json' | wc -l)
if [ "$seed_files" -eq 0 ]; then
    log "No seed JSON files in image — skipping bootstrap hydrate."
    exit 0
fi

log "Empty DB found — ingesting ${seed_files} baked data/*.json snapshots..."
TRACKAROO_DATA_DIR=/app/seed-data python ingest.py
log "Bootstrap hydrate complete."