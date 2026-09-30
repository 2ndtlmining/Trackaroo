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
#   5. wait for the Docker healthcheck (/healthz)
#   6. repair_listings.py dry run; --apply only on an explicit "y"
#   7. /healthz must report this SHA and list umart
#
# Knobs: FORCE=1 (allow RUN_AT_HOUR..RETRY_UNTIL_HOUR), SKIP_BACKUP=1 (no
# running container to back up from -- the first migration, after a manual
# backup), HEALTH_TIMEOUT (s, default 900: a first boot hydrates history).
set -euo pipefail

cd "$(dirname "$0")/.."

SERVICE=trackaroo
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-900}
VERIFY_TIMEOUT=${VERIFY_TIMEOUT:-600}
POLL_SECONDS=${POLL_SECONDS:-10}
RUN_AT_HOUR=${RUN_AT_HOUR:-4}
RETRY_UNTIL_HOUR=${RETRY_UNTIL_HOUR:-9}

log() { printf '[redeploy] %s\n' "$*"; }
die() { printf '[redeploy] ERROR: %s\n' "$*" >&2; exit 1; }

# ── 1. Preflight ─────────────────────────────────────────────────────────
[ -f .env ] || die ".env is missing (copy .env.example and fill it in)"

git diff --quiet && git diff --cached --quiet \
    || die "the checkout has local changes; the deployed SHA would not be the code that runs"

hour=$((10#${REDEPLOY_HOUR:-$(date +%H)}))
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
cid=$(docker compose ps -q "$SERVICE")
waited=0
while :; do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$cid")
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

# ── 6. Repair dry run ────────────────────────────────────────────────────
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

# ── 7. Verify ────────────────────────────────────────────────────────────
# umart appears once the boot catch-up has registered the active retailers,
# which can be a little after the container turns healthy: retry for it.
waited=0
while :; do
    healthz=$(docker compose exec -T "$SERVICE" node -e \
        "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/healthz').then(r=>r.text()).then(t=>console.log(t))" </dev/null)
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
