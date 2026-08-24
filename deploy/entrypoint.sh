#!/bin/sh
# Trackaroo daily-run scheduler (runs inside the `cron` service container).
#
# Runs the full daily pipeline — scrape both retailers, ingest, mirror the DB
# back out to JSON, run health checks, back up the database — once a day at
# RUN_AT_HOUR, plus an immediate catch-up run on boot if today has no snapshot
# yet. A single iteration can be forced with RUN_ONCE=1 (used for one-shot
# `docker run` from a host scheduler).
#
# Scheduling note: this used to be `sleep ${RUN_INTERVAL_HOURS}h` in a loop,
# anchored to container start. That drifts — every restart moved the run time,
# and a restart shortly before the due time could skip a day entirely. The
# schedule is now wall-clock and idempotent per calendar day.
#
# Knobs (env):
#   RUN_AT_HOUR   Local hour to run the pipeline, 0-23 (default 4)
#   TZ            Timezone (default Australia/Melbourne, set in the image)
#   TRACKAROO_DB  SQLite db path (default /app/db/trackaroo.db)

set -e

: "${RUN_AT_HOUR:=4}"
RUN_AT_HOUR_PAD=$(printf '%02d' "$RUN_AT_HOUR")

log() {
    echo "[trackaroo-cron] $(date '+%Y-%m-%d %H:%M:%S %Z') $1"
}

# Ensure the DB exists and hydrate a fresh one from baked-in history
# (idempotent — skips when products/snapshots already exist).
python seed.py
trackaroo-bootstrap-data

run_pipeline() {
    log "Starting daily pipeline..."
    python run_daily.py && log "Pipeline finished." || log "Pipeline finished with errors (retrying next window)."
}

# Has the pipeline already stored snapshots for today's LOCAL date?
todays_run_done() {
    python - <<'PY'
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

db = Path(os.environ.get("TRACKAROO_DB", "/app/db/trackaroo.db"))
if not db.exists():
    sys.exit(1)
try:
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT 1 FROM price_snapshots WHERE snapshot_date = ? LIMIT 1",
        (date.today().isoformat(),),
    ).fetchone()
    conn.close()
except sqlite3.Error:
    sys.exit(1)
sys.exit(0 if row else 1)
PY
}

if [ "$RUN_ONCE" = "1" ]; then
    run_pipeline
    exit 0
fi

# Catch-up: a container that was down over the scheduled hour would otherwise
# lose the day permanently — retailers only expose current prices.
if todays_run_done; then
    log "Today already has snapshots — skipping the boot catch-up run."
else
    log "No snapshots for today yet — running the pipeline now (catch-up)."
    run_pipeline
fi

log "Trackaroo scheduler started (daily at ${RUN_AT_HOUR_PAD}:00 ${TZ:-local})"
while true; do
    sleep 3600
    hour=$(date '+%H')
    if [ "$hour" = "$RUN_AT_HOUR_PAD" ]; then
        if todays_run_done; then
            log "Run window reached but today already has snapshots — nothing to do."
        else
            run_pipeline
        fi
    fi
done
