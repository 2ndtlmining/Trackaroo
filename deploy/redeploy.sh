#!/usr/bin/env bash
# One-command redeploy on the prod host (Phase 6). Run from anywhere:
#   deploy/redeploy.sh
#
#   1. preflight: .env present, clean checkout, outside the scrape window,
#      no leftover non-compose "trackaroo" container
#   2. git pull --ff-only
#   3. back up the DB (inside the running container; mirrors off-host when
#      TRACKAROO_BACKUP_MIRROR_DIR is set)
#   4. build with the git SHA, then up -d
#   5. wait for the Docker healthcheck (/healthz), then for the boot
#      catch-up run to finish (it scrapes and ingests right after boot)
#   6. apply the watchlist (seed.py --allow-bulk: the boot seed refuses a
#      change of more than 5 tracked parts), then the repair_listings.py dry
#      run; --apply only on an explicit "y"
#   7. /healthz must report this SHA and list umart
#
# Knobs: FORCE=1 (allow RUN_AT_HOUR..RETRY_UNTIL_HOUR), SKIP_BACKUP=1 (no
# running container to back up from -- the first migration, after a manual
# backup), HEALTH_TIMEOUT (s, default 900: a first boot hydrates history),
# CATCHUP_TIMEOUT (s, default 1800), VERIFY_TIMEOUT (s, default 600).
set -euo pipefail

cd "$(dirname "$0")/.."

SERVICE=trackaroo
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-900}
CATCHUP_TIMEOUT=${CATCHUP_TIMEOUT:-1800}
VERIFY_TIMEOUT=${VERIFY_TIMEOUT:-600}
POLL_SECONDS=${POLL_SECONDS:-10}

log() { printf '[redeploy] %s\n' "$*"; }
die() { printf '[redeploy] ERROR: %s\n' "$*" >&2; exit 1; }

# An hour setting from .env (the container schedules from there), quotes allowed.
env_hour() { sed -n "s/^$1=[\"']\{0,1\}\([0-9]\{1,2\}\).*/\1/p" .env | tail -n 1; }

# ── 1. Preflight ─────────────────────────────────────────────────────────
[ -f .env ] || die ".env is missing (copy .env.example and fill it in)"

git rev-parse --git-dir >/dev/null 2>&1 \
    || die "$(pwd) is not a git checkout; clone the repo and move db/trackaroo.db* and db/backups/ into it (DEPLOYMENT.md)"
git diff --quiet && git diff --cached --quiet \
    || die "the checkout has local changes; the deployed SHA would not be the code that runs"

# Environment first, then .env, then the entrypoint's defaults.
run_at=${RUN_AT_HOUR:-$(env_hour RUN_AT_HOUR)}
retry_until=${RETRY_UNTIL_HOUR:-$(env_hour RETRY_UNTIL_HOUR)}
RUN_AT_HOUR=$((10#${run_at:-4}))
RETRY_UNTIL_HOUR=$((10#${retry_until:-9}))
# The container runs on Melbourne time; the host may well be on UTC.
hour=$((10#${REDEPLOY_HOUR:-$(TZ=Australia/Melbourne date +%H)}))
if [ "${FORCE:-0}" != "1" ] && [ "$hour" -ge "$RUN_AT_HOUR" ] && [ "$hour" -le "$RETRY_UNTIL_HOUR" ]; then
    die "it is inside the scrape window (${RUN_AT_HOUR}:00-${RETRY_UNTIL_HOUR}:59); recreating now kills a scrape. Re-run later, or with FORCE=1"
fi

if [ -n "$(docker ps -a --filter "name=^${SERVICE}$" -q)" ] \
    && [ -z "$(docker ps -a --filter "name=^${SERVICE}$" --filter label=com.docker.compose.project -q)" ]; then
    die "a container named ${SERVICE} exists that compose did not create (the old docker run one). Stop it and keep it for rollback: docker stop ${SERVICE} && docker rename ${SERVICE} ${SERVICE}-old"
fi

# ── 2. Pull ──────────────────────────────────────────────────────────────
git pull --ff-only
sha=$(git rev-parse --short HEAD)
log "deploying ${sha}"

# ── 3. Backup ────────────────────────────────────────────────────────────
if [ -n "$(docker compose ps -q --status running "$SERVICE")" ]; then
    docker compose exec -T "$SERVICE" python backup_db.py </dev/null \
        || die "pre-deploy backup failed; nothing was changed"
elif [ "${SKIP_BACKUP:-0}" = "1" ]; then
    log "SKIP_BACKUP=1: no pre-deploy backup"
else
    die "no running ${SERVICE} container to back up from. Back up db/ by hand, then re-run with SKIP_BACKUP=1"
fi

# ── 4. Build and start ───────────────────────────────────────────────────
GIT_SHA="$sha" docker compose build
docker compose up -d

# ── 5. Wait for healthy ──────────────────────────────────────────────────
cid=$(docker compose ps -q "$SERVICE" || true)
[ -n "$cid" ] || { docker compose logs --tail 50 "$SERVICE" >&2 || true; die "no ${SERVICE} container after up -d"; }
waited=0
while :; do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>&1 || true)
    [ "$status" = healthy ] && break
    if [ "$waited" -ge "$HEALTH_TIMEOUT" ]; then
        docker compose logs --tail 50 "$SERVICE" >&2 || true
        die "container not healthy after ${HEALTH_TIMEOUT}s (last status: ${status})"
    fi
    sleep "$POLL_SECONDS"
    waited=$((waited + POLL_SECONDS))
    [ "$POLL_SECONDS" -gt 0 ] || waited=$((waited + 1))
done
log "healthy"

# The entrypoint starts the boot catch-up (scrape + ingest of whatever today
# still lacks) right after the dashboard, so "healthy" comes before it ends.
# A repair alongside that ingest would race it; wait for its log line (both
# outcomes log "Pipeline finished").
waited=0
caught_up=0
while :; do
    if docker compose logs --no-color "$SERVICE" 2>/dev/null | grep -q 'Pipeline finished'; then
        caught_up=1
        break
    fi
    [ "$waited" -lt "$CATCHUP_TIMEOUT" ] || break
    sleep "$POLL_SECONDS"
    waited=$((waited + POLL_SECONDS))
    [ "$POLL_SECONDS" -gt 0 ] || waited=$((waited + 1))
done

# ── 6. Watchlist, then repair dry run ────────────────────────────────────
if [ "$caught_up" = 1 ]; then
    # The boot seed refuses more than 5 tracked flips (a retirement or a
    # rollover) and the container carries on, so a merged watchlist PR would
    # silently never apply. The PR was the review; apply it here. Seed runs
    # before the repair so a listing can be re-pointed to a part it adds.
    log "applying db/watchlist.csv (seed.py --allow-bulk)"
    docker compose exec -T "$SERVICE" python seed.py --allow-bulk </dev/null         || die "seed.py failed (see above); the watchlist is not applied. Fix it, then: docker compose exec ${SERVICE} python seed.py --allow-bulk"
    # </dev/null on every exec: `exec -T` still forwards stdin, so the dry run
    # would otherwise swallow the operator's answer below.
    docker compose exec -T "$SERVICE" python repair_listings.py </dev/null
    answer=""
    read -r -p "[redeploy] Apply these repairs? [y/N] " answer || answer=""
    answer=${answer%$'\r'}  # a CRLF terminal
    if [ "$answer" = y ] || [ "$answer" = Y ]; then
        docker compose exec -T "$SERVICE" python repair_listings.py --apply </dev/null
    else
        log "repairs not applied. To apply later: docker compose exec ${SERVICE} python repair_listings.py --apply"
    fi
else
    log "WARNING: the boot catch-up had not finished after ${CATCHUP_TIMEOUT}s; watchlist and repair skipped so they cannot race the ingest."
    log "Once 'Pipeline finished' shows in docker compose logs ${SERVICE}, run: docker compose exec ${SERVICE} python seed.py --allow-bulk"
    log "Once 'Pipeline finished' shows in docker compose logs ${SERVICE}, run: docker compose exec ${SERVICE} python repair_listings.py (then --apply)"
fi

# ── 7. Verify ────────────────────────────────────────────────────────────
# seed.py registers the active retailers before the dashboard starts, so
# umart should show at once; the retry only covers a slow first request.
waited=0
while :; do
    healthz=$(docker compose exec -T "$SERVICE" node -e \
        "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/healthz').then(r=>r.text()).then(t=>console.log(t))" </dev/null) \
        || die "could not reach /healthz inside the container: ${healthz:-no output}"
    printf '%s' "$healthz" | grep -q '"ok":true' || die "/healthz is not ok: ${healthz}"
    printf '%s' "$healthz" | grep -q "\"version\":\"${sha}\"" || die "/healthz does not report ${sha}; another build is running"
    printf '%s' "$healthz" | grep -q '"retailer":"umart"' && break
    [ "$waited" -lt "$VERIFY_TIMEOUT" ] || die "/healthz does not list umart after ${VERIFY_TIMEOUT}s"
    sleep "$POLL_SECONDS"
    waited=$((waited + POLL_SECONDS))
    [ "$POLL_SECONDS" -gt 0 ] || waited=$((waited + 1))
done
printf '%s\n' "$healthz"
log "done: ${sha} is live"
