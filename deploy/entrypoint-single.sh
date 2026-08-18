#!/bin/sh
# Trackaroo all-in-one entrypoint.
#
# Runs everything a self-hosted Trackaroo needs in ONE container:
#   1. Seed/init the SQLite DB if it doesn't exist yet.
#   2. Start the SvelteKit dashboard (served by node on PORT, default 3000).
#   3. Run the daily pipeline (scrape → ingest → health checks → backup)
#      immediately, then every RUN_INTERVAL_HOURS (default 24).
#   4. Run the spec sync (sync_specs.py) once a week at SPEC_SYNC_DOW @
#      SPEC_SYNC_HOUR (default Sunday 03:00), clear of the daily price run.
#
# Knobs (env):
#   RUN_INTERVAL_HOURS   Pipeline cadence (default 24)
#   BACKUP_KEEP          Backups to retain (default 14)
#   PORT                 Dashboard listen port (default 3000)
#   HOST                 Dashboard bind host (default 0.0.0.0)
#   TRACKAROO_DB         SQLite db path (default /data/trackaroo.db)
#   SPEC_SYNC_DOW        Spec-sync day of week, cron style 0=Sun..6=Sat (default 0)
#   SPEC_SYNC_HOUR       Spec-sync hour of day, 0-23 (default 3)
#   DISCORD_WEBHOOK_GPU  Discord webhook for the GPU digest (optional)
#   DISCORD_WEBHOOK_CPU  Discord webhook for the CPU digest (optional)
#   TRACKAROO_PUBLIC_BASE_URL  Public dashboard URL, adds Trackaroo links to
#                        the Discord digest (optional)
#
# A single pipeline iteration can be run and then exit with RUN_ONCE=1
# (used for one-shot `docker run` from a host crontab).

set -e

: "${RUN_INTERVAL_HOURS:=24}"
: "${BACKUP_KEEP:=14}"
: "${SPEC_SYNC_DOW:=0}"
: "${SPEC_SYNC_HOUR:=3}"
# Zero-pad the hour so it compares cleanly against `date +%H` ("03" not "3").
SPEC_SYNC_HOUR_PAD=$(printf '%02d' "$SPEC_SYNC_HOUR")

log() {
    echo "[trackaroo] $(date '+%Y-%m-%d %H:%M:%S') $1"
}

run_pipeline() {
    log "Starting daily pipeline..."
    python run_daily.py --backup "${BACKUP_KEEP}" && log "Pipeline finished." || log "Pipeline finished with errors (retrying next interval)."
}

run_spec_sync() {
    log "Starting weekly spec sync..."
    python sync_specs.py && log "Spec sync finished." || log "Spec sync finished with errors (retrying next week)."
}

# Weekly spec sync: poll hourly; when the local time hits SPEC_SYNC_DOW @
# SPEC_SYNC_HOUR, run sync_specs.py once that day. The last_run guard makes a
# mid-window container restart re-run it (safe — sync_specs upserts).
spec_sync_loop() {
    last_run=""
    while true; do
        # cron-style DOW: 0=Sun..6=Sat (GNU date %u is 1=Mon..7=Sun, so mod 7).
        dow=$(( $(date '+%u') % 7 ))
        hour=$(date '+%H')
        today=$(date '+%Y-%m-%d')
        if [ "$dow" = "$SPEC_SYNC_DOW" ] && [ "$hour" = "$SPEC_SYNC_HOUR_PAD" ] && [ "$last_run" != "$today" ]; then
            run_spec_sync
            last_run="$today"
        fi
        sleep 3600
    done
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
# Weekly spec sync runs in its own background loop (see spec_sync_loop).
spec_sync_loop &

run_pipeline
log "Scheduler started (interval: ${RUN_INTERVAL_HOURS}h, spec sync: dow ${SPEC_SYNC_DOW} @ ${SPEC_SYNC_HOUR_PAD}:00)"
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