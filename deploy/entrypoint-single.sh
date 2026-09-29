#!/bin/sh
# Trackaroo all-in-one entrypoint.
#
# Runs everything a self-hosted Trackaroo needs in ONE container:
#   1. Seed/init the SQLite DB if it doesn't exist yet.
#   2. Start the SvelteKit dashboard (served by node on PORT, default 3000).
#   3. Run the daily pipeline (scrape -> ingest -> health checks -> backup)
#      once a day at RUN_AT_HOUR, retrying hourly (per retailer) up to
#      RETRY_UNTIL_HOUR, plus an immediate catch-up run on boot for whatever
#      today is still missing (#8).
#   4. Run the spec sync (sync_specs.py) once a week at SPEC_SYNC_DOW @
#      SPEC_SYNC_HOUR (default Sunday 03:00), clear of the daily price run.
#   5. Run the staleness monitor (check_staleness.py) once a day at
#      STALENESS_CHECK_HOUR (default 10:00) to catch a pipeline run that
#      never happened at all.
#
# Scheduling note: this used to be `sleep ${RUN_INTERVAL_HOURS}h` in a loop,
# anchored to container start. That drifts — every restart moved the run time,
# and a restart shortly before the due time could skip a day entirely (16-Aug
# and 23-Aug 2026 were both lost that way). The schedule is now wall-clock:
# run_daily.py itself decides what is left to do (#8) -- the container just
# calls it hourly with --scheduled, which is a no-op outside
# RUN_AT_HOUR..RETRY_UNTIL_HOUR and only scrapes retailers not yet complete
# today, so restarts cannot shift, skip, or double a day.
#
# Knobs (env):
#   RUN_AT_HOUR          Local hour to run the pipeline, 0-23 (default 4)
#   RETRY_UNTIL_HOUR     Last local hour (0-23, default 9) at which a retailer that
#                        failed or came back incomplete today is retried. Retries
#                        run hourly from RUN_AT_HOUR. Keep it EARLIER than
#                        STALENESS_CHECK_HOUR so the monitor judges a finished day.
#   TRACKAROO_BACKUP_KEEP  DB backups to retain (default 14; automatic)
#   PORT                 Dashboard listen port (default 3000)
#   HOST                 Dashboard bind host (default 0.0.0.0)
#   TRACKAROO_DB         SQLite db path (default /app/db/trackaroo.db)
#   TZ                   Timezone (default Australia/Melbourne, set in the image)
#   SPEC_SYNC_DOW        Spec-sync day of week, cron style 0=Sun..6=Sat (default 0)
#   SPEC_SYNC_HOUR       Spec-sync hour of day, 0-23 (default 3)
#   STALENESS_CHECK_HOUR Staleness-monitor hour, 0-23 (default 10). Must be
#                        LATER than RETRY_UNTIL_HOUR: before the last hourly
#                        retry has had its chance, "no data today" is not yet
#                        an outage. Leave at least an hour of gap -- the retry
#                        loop ticks hourly from whenever the container booted
#                        (not necessarily on the hour) and drifts by however
#                        long each pipeline run takes, so a retry started late
#                        in its hour can still be running a few minutes into
#                        the next one.
#   DISCORD_WEBHOOK_ALERT  Webhook the staleness monitor posts to. Unset means
#                        the check still runs but signals only via the log.
#   DISCORD_WEBHOOK_URL  Discord webhook for the CPU+GPU digest (optional)
#   TRACKAROO_PUBLIC_BASE_URL  Public dashboard URL, adds Trackaroo links to
#                        the Discord digest (optional)
#   TRACKAROO_DISCORD_WEBHOOK_URL / TRACKAROO_SMTP_* / TRACKAROO_ALERT_WEBHOOK_URL
#                        Price-alert delivery (check_alerts.py) — all optional,
#                        see .env.example
#
# A single pipeline iteration can be run and then exit with RUN_ONCE=1
# (used for one-shot `docker run` from a host scheduler).

set -e

: "${RUN_AT_HOUR:=4}"
: "${RETRY_UNTIL_HOUR:=9}"
# run_daily.py reads both (config.py), so export the defaults too.
export RUN_AT_HOUR RETRY_UNTIL_HOUR
: "${SPEC_SYNC_DOW:=0}"
: "${SPEC_SYNC_HOUR:=3}"
: "${STALENESS_CHECK_HOUR:=10}"
# Zero-pad the hours so they compare cleanly against `date +%H` ("03" not "3").
RUN_AT_HOUR_PAD=$(printf '%02d' "$RUN_AT_HOUR")
SPEC_SYNC_HOUR_PAD=$(printf '%02d' "$SPEC_SYNC_HOUR")
STALENESS_CHECK_HOUR_PAD=$(printf '%02d' "$STALENESS_CHECK_HOUR")

log() {
    echo "[trackaroo] $(date '+%Y-%m-%d %H:%M:%S %Z') $1"
}

# run_daily.py decides what is left to do (#8): --pending-only scrapes only the
# retailers without a complete run today; --scheduled additionally does
# nothing outside RUN_AT_HOUR..RETRY_UNTIL_HOUR. Both are no-ops once every
# retailer is done, so calling them hourly is cheap and restart-safe.
run_pipeline() {
    log "Starting pipeline $*..."
    python run_daily.py "$@" && log "Pipeline finished." || log "Pipeline finished with errors (failed retailers retry hourly until ${RETRY_UNTIL_HOUR}:59)."
}

run_spec_sync() {
    log "Starting weekly spec sync..."
    python sync_specs.py && log "Spec sync finished." || log "Spec sync finished with errors (retrying next week)."
}

# Every other health check runs INSIDE run_daily.py, so none of them can fire
# when the pipeline does not run at all -- exactly what happened on 27-Aug-2026,
# where a human noticed the missing day before the system did. This one reads
# the DB only (no scraping, no writes), so it is safe on any schedule.
run_staleness_check() {
    log "Running staleness check..."
    python check_staleness.py && log "Staleness check: data is fresh." || log "Staleness check FAILED - data is stale (see alert)."
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

# Daily staleness monitor: same hourly-poll shape as spec_sync_loop. The
# last_run guard keeps it to once a day; a restart inside the window re-runs it,
# which is harmless because the check is read-only.
staleness_loop() {
    last_run=""
    while true; do
        hour=$(date '+%H')
        today=$(date '+%Y-%m-%d')
        if [ "$hour" = "$STALENESS_CHECK_HOUR_PAD" ] && [ "$last_run" != "$today" ]; then
            run_staleness_check
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
# State the container port explicitly. Publishing `-p 2222:2222` without
# also setting PORT is a silent failure: Docker reports the container as
# healthy, but nothing inside is listening on 2222 and every request hangs.
log "Dashboard listening INSIDE the container on port ${PORT}"
log "Publish it with:  -p <HOST_PORT>:${PORT}   (right-hand number must be ${PORT}; set PORT to change it)"
node web/server.js &
WEB_PID=$!
log "Dashboard started."

if [ "$RUN_ONCE" = "1" ]; then
    run_pipeline
    log "RUN_ONCE mode — stopping dashboard and exiting."
    kill "$WEB_PID"
    wait "$WEB_PID" 2>/dev/null || true
    exit 0
fi

# ── 3. Pipeline scheduler ─────────────────────────────────────────────────
# Weekly spec sync runs in its own background loop (see spec_sync_loop).
spec_sync_loop &
staleness_loop &

# Catch-up: if the container was down over the run hour, whatever today is
# still missing would be lost permanently (retailers only expose current
# prices). Scrape only that, whatever the hour.
run_pipeline --pending-only

log "Scheduler started (daily at ${RUN_AT_HOUR_PAD}:00 ${TZ:-local}, failed retailers retried hourly until ${RETRY_UNTIL_HOUR}:59, spec sync: dow ${SPEC_SYNC_DOW} @ ${SPEC_SYNC_HOUR_PAD}:00, staleness check @ ${STALENESS_CHECK_HOUR_PAD}:00)"
while true; do
    sleep 3600 &
    sleep_pid=$!
    wait "$sleep_pid"

    # Keep the dashboard reachable even if the web process exits early.
    if ! kill -0 "$WEB_PID" 2>/dev/null; then
        log "Dashboard exited; restarting."
        node web/server.js &
        WEB_PID=$!
    fi

    run_pipeline --scheduled
done
