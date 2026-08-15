#!/bin/sh
# Trackaroo all-in-one entrypoint.
#
# Runs everything a self-hosted Trackaroo needs in ONE container:
#   1. Seed/init the SQLite DB if it doesn't exist yet.
#   2. Start the SvelteKit dashboard (served by node on PORT, default 3000).
#   3. Run the daily pipeline (scrape → ingest → health checks → backup)
#      immediately, then every RUN_INTERVAL_HOURS (default 24).
#
# Knobs (env):
#   RUN_INTERVAL_HOURS   Pipeline cadence (default 24)
#   BACKUP_KEEP          Backups to retain (default 14)
#   PORT                 Dashboard listen port (default 3000)
#   HOST                 Dashboard bind host (default 0.0.0.0)
#   TRACKAROO_DB         SQLite db path (default /data/trackaroo.db)
#
# A single pipeline iteration can be run and then exit with RUN_ONCE=1
# (used for one-shot `docker run` from a host crontab).

set -e

: "${RUN_INTERVAL_HOURS:=24}"
: "${BACKUP_KEEP:=14}"

log() {
    echo "[trackaroo] $(date '+%Y-%m-%d %H:%M:%S') $1"
}

run_pipeline() {
    log "Starting daily pipeline..."
    python run_daily.py --backup "${BACKUP_KEEP}" && log "Pipeline finished." || log "Pipeline finished with errors (retrying next interval)."
}

# ── 1. Ensure the DB exists (init empty DB + seed watchlist) ──────────────
python seed.py

# ── 1b. Bootstrap: hydrate a fresh DB with baked-in snapshot history ──────
trackaroo-bootstrap-data

# ── 2. Start the dashboard in the background ──────────────────────────────
log "Starting dashboard on :${PORT}"
node web/build/index.js &
WEB_PID=$!
log "Dashboard started."

if [ "$RUN_ONCE" = "1" ]; then
    run_pipeline
    log "RUN_ONCE mode — stopping dashboard and exiting."
    kill "$WEB_PID"
    wait "$WEB_PID" 2>/dev/null || true
    exit 0
fi

# ── 3. Pipeline scheduler loop ────────────────────────────────────────────
run_pipeline
log "Scheduler started (interval: ${RUN_INTERVAL_HOURS}h)"
while true; do
    log "Sleeping for ${RUN_INTERVAL_HOURS}h..."
    sleep "${RUN_INTERVAL_HOURS}h" &
    sleep_pid=$!
    # Keep the dashboard reachable even if the web process exits early:
    wait "$sleep_pid"
    if ! kill -0 "$WEB_PID" 2>/dev/null; then
        log "Dashboard exited; restarting."
        node web/build/index.js &
        WEB_PID=$!
    fi
    run_pipeline
done