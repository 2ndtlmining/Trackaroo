#!/bin/sh
# Trackaroo daily-run scheduler (runs inside the `cron` service container).
#
# Runs the full daily pipeline on a fixed interval: scrape both retailers,
# ingest, run health checks, and back up the database. The interval is
# configurable via RUN_INTERVAL_HOURS (default 24). A single iteration can
# be forced with RUN_ONCE=1 (used for one-shot `docker run` from a host
# crontab).

set -e

: "${RUN_INTERVAL_HOURS:=24}"
: "${BACKUP_KEEP:=14}"

log() {
    echo "[trackaroo-cron] $(date '+%Y-%m-%d %H:%M:%S') $1"
}

run_pipeline() {
    log "Starting daily pipeline..."
    python run_daily.py --backup "${BACKUP_KEEP}"
    log "Pipeline finished (exit $?)."
}

if [ "$RUN_ONCE" = "1" ]; then
    run_pipeline
    exit 0
fi

log "Trackaroo scheduler started (interval: ${RUN_INTERVAL_HOURS}h)"
while true; do
    run_pipeline
    log "Sleeping for ${RUN_INTERVAL_HOURS}h..."
    sleep "${RUN_INTERVAL_HOURS}h"
done