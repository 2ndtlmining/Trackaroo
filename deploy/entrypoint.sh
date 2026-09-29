#!/bin/sh
# Trackaroo daily-run scheduler (runs inside the `cron` service container).
#
# Runs the full daily pipeline — scrape both retailers, ingest, mirror the DB
# back out to JSON, run health checks, back up the database — once a day at
# RUN_AT_HOUR, retrying hourly (per retailer) up to RETRY_UNTIL_HOUR, plus an
# immediate catch-up run on boot for whatever today is still missing (#8). A
# single iteration can be forced with RUN_ONCE=1 (used for one-shot
# `docker run` from a host scheduler).
#
# Scheduling note: this used to be `sleep ${RUN_INTERVAL_HOURS}h` in a loop,
# anchored to container start. That drifts — every restart moved the run time,
# and a restart shortly before the due time could skip a day entirely. The
# schedule is now wall-clock: run_daily.py itself decides what is left to do
# (#8) -- this script just calls it hourly with --scheduled.
#
# Knobs (env):
#   RUN_AT_HOUR       Local hour to run the pipeline, 0-23 (default 4)
#   RETRY_UNTIL_HOUR  Last local hour (0-23, default 9) at which a retailer
#                     that failed or came back incomplete today is retried.
#                     Retries run hourly from RUN_AT_HOUR.
#   TZ                Timezone (default Australia/Melbourne, set in the image)
#   TRACKAROO_DB      SQLite db path (default /app/db/trackaroo.db)

set -e

: "${RUN_AT_HOUR:=4}"
: "${RETRY_UNTIL_HOUR:=9}"
# run_daily.py reads both (config.py), so export the defaults too.
export RUN_AT_HOUR RETRY_UNTIL_HOUR
RUN_AT_HOUR_PAD=$(printf '%02d' "$RUN_AT_HOUR")

log() {
    echo "[trackaroo-cron] $(date '+%Y-%m-%d %H:%M:%S %Z') $1"
}

# Ensure the DB exists and hydrate a fresh one from baked-in history
# (idempotent — skips when products/snapshots already exist).
python seed.py
trackaroo-bootstrap-data

# run_daily.py decides what is left to do (#8): --pending-only scrapes only the
# retailers without a complete run today; --scheduled additionally does
# nothing outside RUN_AT_HOUR..RETRY_UNTIL_HOUR. Both are no-ops once every
# retailer is done, so calling them hourly is cheap and restart-safe.
run_pipeline() {
    log "Starting pipeline $*..."
    python run_daily.py "$@" && log "Pipeline finished." || log "Pipeline finished with errors (failed retailers retry hourly until ${RETRY_UNTIL_HOUR}:59)."
}

if [ "$RUN_ONCE" = "1" ]; then
    run_pipeline
    exit 0
fi

# Catch-up: a container that was down over the run hour would otherwise lose
# whatever today is still missing permanently — retailers only expose current
# prices. Scrape only that, whatever the hour.
run_pipeline --pending-only

log "Trackaroo scheduler started (daily at ${RUN_AT_HOUR_PAD}:00 ${TZ:-local}, failed retailers retried hourly until ${RETRY_UNTIL_HOUR}:59)"
while true; do
    sleep 3600
    run_pipeline --scheduled
done
