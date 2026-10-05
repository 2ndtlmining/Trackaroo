# Trackaroo Deployment

Self-hosted deployment for the daily tracker + dashboard.

**One Docker image runs everything**, started with plain `docker run` — there is
no docker-compose. The container serves the SvelteKit dashboard on :3000 and
runs the daily pipeline (scrape both retailers → validate JSON → ingest →
mirror the DB back out to JSON → health-check → back up the DB) once a day on a
wall clock.

Running the Python pipeline natively (`python run_daily.py`) is fully supported
alongside or instead of the container; both use the same `db/` and `data/`
directories.

> **Changed 23-Aug-2026.** Three defaults were wrong in ways that lost data:
>
> - The stack used a **named volume** (and the live container had *no mount at
>   all*), so scraped data lived inside Docker and vanished on `docker rm`. The
>   documented run now bind-mounts the repo's own `db/` and `data/`.
> - Containers ran on **UTC**. The scrapers stamp snapshots with the local
>   date, so a run before 10:00 AEST filed data under the previous day. The
>   image installs `tzdata` and pins `TZ=Australia/Melbourne`.
> - Scheduling was `sleep ${RUN_INTERVAL_HOURS}h` anchored to container start,
>   which drifted on every restart and could skip a day. It is now a wall-clock
>   `RUN_AT_HOUR` (default 04:00 local) plus a catch-up run on boot when today
>   has no data. **`RUN_INTERVAL_HOURS` is no longer used.**
>
> `docker-compose.yml` was removed in the same change; recover it with
> `git show HEAD:docker-compose.yml` if you ever want the two-service split.

---

## Option A — Docker Compose (recommended)

```bash
cp .env.example .env            # once; fill in webhooks etc.
deploy/redeploy.sh              # pull, back up, build, start, verify
```

`docker-compose.yml` holds the one `trackaroo` service: the image built with
the git SHA as `GIT_SHA`, `./db`, `./data` and `./logs` bind-mounted,
`restart: unless-stopped`, `.env` as the env file, Docker log rotation
(10 MB x 5), and a label that keeps watchtower from replacing it (the image
is built locally, never pulled). By hand:

```bash
GIT_SHA=$(git rev-parse --short HEAD) docker compose build
docker compose up -d
```

Compose resolves the relative mounts itself, so the Git Bash path mangling
described below does not apply to it. Host-only extras (the NAS backup
mirror) go in `docker-compose.override.yml` (gitignored), which compose merges
automatically; start from `docker-compose.override.example.yml`.

**Never `docker compose up` in a development checkout**: it mounts that
checkout's `db/` and starts a live retailer scrape.

### Plain `docker run`

Still works (same image, same mounts); kept for one-off runs and the
entrypoint overrides. Build, then run it with the DB and snapshots mapped onto
the host, so the data outlives the container:

```bash
docker build -t trackaroo .
```

```bash
docker run -d --name trackaroo \
  -p 3000:3000 \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/db:/app/db" \
  -v "$(pwd)/data:/app/data" \
  trackaroo
```

PowerShell uses backticks and `${PWD}` — see [README.md](README.md#docker-single-all-in-one-container)
for that form, the named-volume alternative, and the pipeline-only /
dashboard-only entrypoint overrides.

> **Git Bash on Windows mangles the `-v` paths and the failure is silent.**
> MSYS rewrites POSIX-looking arguments, so `-v "$(pwd)/db:/app/db"` reaches
> Docker with the destination turned into a Windows path under
> `\Program Files\Git\...` and a `;C` suffix glued onto the source. The
> container starts, reports healthy and serves the dashboard — while writing to
> its own layer, which is the exact state that cost this project 165 snapshots.
> The tell is a `db;C` / `data;C` directory appearing in the repo root.
> Prefix the command with `MSYS_NO_PATHCONV=1`, or use PowerShell. Always
> confirm the mounts landed:
>
> ```bash
> docker inspect trackaroo --format '{{range .Mounts}}{{.Source}} {{.Destination}}{{println}}{{end}}'
> ```
>
> The destinations must read `/app/db` and `/app/data`. Linux and macOS hosts
> are unaffected.

| Mount | Contents |
|---|---|
| `./db` → `/app/db` | `trackaroo.db` (SQLite, WAL), `backups/`, `schema.sql`, `watchlist.csv` |
| `./data` → `/app/data` | `{cpu,gpu}_{scorptec,pccg}_DD_Month_YYYY.json` daily snapshots |

Map **both**. `data/*.json` is the backup the DB is rebuilt from
(`python ingest.py`), so a container with only `/app/db` mapped still loses the
backup on `docker rm`.

**Docker Desktop (Windows / macOS): never write to the mounted DB from the host
while the container runs.** The DB is in WAL mode, and WAL coordinates writers
through shared memory in `trackaroo.db-shm`. Docker Desktop's bind mounts cross
a VM boundary, so that shared memory is not coherent between a host process and
the container: a native `python run_daily.py`, `seed.py` or `repair_listings.py`
on the host can corrupt the DB or lose writes. Run those inside the container
instead (`docker compose exec trackaroo python seed.py`), or stop the container
first. A native Linux host (like the production server) shares one kernel and
is unaffected. The run lock (`db/run_daily.lock`) stops two pipeline runs
overlapping, but it does not make host-side writes safe here.

| Setting | Default | Override (in `.env`; `-e X=Y` with `docker run`) |
|---|---|---|
| Daily run hour (local) | `04` | `RUN_AT_HOUR=6` |
| Last hourly retry of a failed retailer | `09` | `RETRY_UNTIL_HOUR=8` (keep it before `STALENESS_CHECK_HOUR`) |
| Staleness monitor hour | `10` | `STALENESS_CHECK_HOUR=11` |
| Timezone | `Australia/Melbourne` | `TZ` under `environment:` in `docker-compose.yml` |
| Backups retained (days, newest per day) | 14 | `TRACKAROO_BACKUP_KEEP=30` |
| Dashboard host port | 3000 | `TRACKAROO_PORT=8080` (compose reads it from the shell or `.env`); `-p 8080:3000` |
| Spec-sync day / hour | Sun / 03 | `SPEC_SYNC_DOW=1`, `SPEC_SYNC_HOUR=12` |

On boot the container seeds the DB if missing, hydrates a fresh one from the
snapshot history baked into the image (a no-op once snapshots exist), starts
the dashboard, and scrapes **whatever today is still missing**
(`run_daily.py --pending-only`). From then on it calls
`run_daily.py --scheduled` hourly. That runs the pipeline from `RUN_AT_HOUR`
and retries each retailer whose run today failed, timed out, came back empty or
was skipped by a cooldown, until `RETRY_UNTIL_HOUR`. The digest and an
identical alert go out at most once a day. Every real run ends with a verified
DB backup.

### Choosing the dashboard port

The app listens on port **3000 inside the container**. When publishing it, the
**right-hand number must be 3000**:

```bash
-p 3000:3000     # localhost:3000
-p 8080:3000     # localhost:8080
-p 2222:3000     # localhost:2222
```

To change the *container* port you must set `PORT` as well, so both halves match:

```bash
docker run -e PORT=2222 -p 2222:2222 ... trackaroo
```

**`-p 2222:2222` without `PORT=2222` fails silently** — Docker reports the
container as `Up`, but nothing inside is listening on 2222, so every request
hangs. The startup log states the container port explicitly; check
`docker logs trackaroo` if the dashboard is unreachable.

### Verifying a deployment

```bash
docker exec trackaroo date                    # local time, not UTC
docker inspect trackaroo --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}
{{end}}'
docker exec trackaroo python -c "import sqlite3;print(sqlite3.connect('/app/db/trackaroo.db').execute('select max(snapshot_date),count(*) from price_snapshots').fetchone())"
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/
```

### Redeploying

```bash
deploy/redeploy.sh
```

1. Preflight: `.env` present, a git checkout with no local changes, not
   between `RUN_AT_HOUR` and `RETRY_UNTIL_HOUR` in Melbourne time (read from
   `.env` like the container does; a recreate kills a running scrape;
   `FORCE=1` overrides), and no leftover non-compose `trackaroo` container.
2. `git pull --ff-only`.
3. `python backup_db.py` inside the running container (verified with
   `quick_check`; also mirrored off-host when `TRACKAROO_BACKUP_MIRROR_DIR` is set).
4. `docker compose build` with `GIT_SHA`, then `docker compose up -d`. The
   entrypoint runs `migrate.py` and `seed.py` on boot.
5. Waits for the Docker healthcheck (`HEALTH_TIMEOUT`, default 900 s), then
   for the boot catch-up run to log "Pipeline finished" (`CATCHUP_TIMEOUT`,
   default 1800 s): it scrapes and ingests right after boot, and a repair
   alongside it would race the ingest.
6. `repair_listings.py` dry run; asks before `--apply`. With no terminal
   (cron, piped ssh) it never applies. If the catch-up had not finished, the
   repair is skipped and the command to run later is printed.
7. `/healthz` must report the SHA just built and list `umart`.

It exits non-zero at the first failed step. Before step 4 nothing has changed.
The data is in the mounts, not the container, so a redeploy is non-destructive.

### Moving from `docker run` to compose (once)

For the prod server (`giel@dockerhost:~/docker/Trackaroo`) there is a
copy-paste, step-by-step version of this:
[docs/runbooks/dockerhost-compose-migration.md](docs/runbooks/dockerhost-compose-migration.md).

Nothing here deletes data. Do it outside 04:00–09:59.

1. Find the old container's mounts and note both source paths:
   `docker inspect trackaroo --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'`
2. Back up, twice over:
   - `docker exec trackaroo python backup_db.py` (a verified SQLite copy in
     `db/backups/`), then copy that newest backup to `db/pre-compose.db`.
     That copy is step 6's reference: backups in `db/backups/` are pruned
     (the newest per day plus the 3 newest overall), and migration day
     writes several;
   - `docker stop trackaroo`, then a byte-for-byte archive of both mounts
     taken while nothing writes:
     `tar czf ~/trackaroo-pre-compose-$(date +%F).tgz -C <project dir> db data`,
     copied off the host.
3. Keep the old container and image for rollback, and note the code it ran:
   `docker rename trackaroo trackaroo-old && docker tag trackaroo:latest trackaroo:pre-compose`,
   and `git rev-parse HEAD` in the checkout if it is one. Keep both for a week.
4. The directory compose runs from must be a git checkout of this repo
   (`git -C <dir> rev-parse HEAD` succeeds), and its `./db` and `./data` must
   be the data from step 1. `db/` also holds **tracked** files
   (`schema.sql`, `watchlist.csv`, `watchlist.py`, `launch_msrp.json`) that
   the mount lays over the image's copies, so when the data has to move into
   a fresh clone, move **only** `db/trackaroo.db*`, `db/backups/`,
   `db/pre-compose.db` and the whole `data/` — never replace the clone's `db/`
   directory.
   Check `.env` before the first compose start: compose parses it differently
   from `docker run --env-file` (it strips quotes and expands `$`). A value
   containing `$` (a password, a webhook) must have each `$` written as `$$`.
5. `SKIP_BACKUP=1 deploy/redeploy.sh` (step 2 was the backup). Answer `y` to
   the repair after reading the dry run (see "Repair mis-filed listings").
6. Nothing was lost: `docker compose exec trackaroo python restore_drill.py --backup /app/db/pre-compose.db`
   must pass (the live DB has at least as many snapshots on every day the
   pre-deploy backup holds). Also check the headline cases on the site: the
   RTX 5060 Ti headline is a 16GB card and "GeForce RTX 5060 Ti 8GB" has its
   own page; the RTX 5090 has no ghost listings; `/deals` shows nothing under
   2% or $10; the footer says `build <sha>`.
7. A week later, if nothing needed rolling back:
   `docker rm trackaroo-old && docker rmi trackaroo:pre-compose`. Keep the
   tarball and `db/pre-compose.db`.

**Rollback** (within that week). The old container mounts the same `db/`,
whose tracked files are now the new code's, so restore the old code too:

1. `docker compose down`
2. `git checkout <the SHA noted in step 3>` (skip if it was not a checkout)
3. Optional, to undo the migration and repairs as well (nothing is running now):
   `cp db/pre-compose.db db/trackaroo.db && rm -f db/trackaroo.db-wal db/trackaroo.db-shm`.
   Prices scraped since the move stay in `data/*.json` and can be re-ingested
   later; without this step the old code runs on the migrated DB, whose
   changes are additive.
4. `docker rename trackaroo-old trackaroo && docker start trackaroo`

List pages (`/`, `/deals`, `/movers`, `/products`) send
`cache-control: public, max-age=60, stale-while-revalidate=300`, so for a few
minutes after a redeploy a browser may still show a pre-deploy page it served
stale-while-revalidate style. Hard-refresh (Ctrl+F5) if you need to confirm
the new build is live.

### Repair mis-filed listings

`repair_listings.py` re-applies the current watchlist matcher (`scraper/chip_key.py`)
to every existing listing, so a matcher fix (e.g. #1, #2) also corrects listings
filed under the wrong product *before* the fix shipped. (`ingest.py` also
re-points a listing on its own the next time it sees a *current* snapshot that
resolves differently — see #1/#2 in `find_or_create_listing` — but that only
fires on the next scrape; this script fixes everything immediately.) It never
deletes a `price_snapshots` row; a listing that no longer matches any tracked
product is moved to a `tracked=0` "Unmatched CPU/GPU listing" holding product
and marked `stale`, taking its prices out of the wrong product's history
without discarding them.

Before `--apply`, review any `UNMATCHED` **GPU** line whose title has no
memory size (e.g. a bundle or "AI Box" listing) — the matcher resolves GPUs
by chip key *and* VRAM, so a title lacking a size can only ever be unmatched
here, but if the retailer's own description (not the title) names the VRAM,
the next scrape can still re-point it away from the holding product later.

After pulling a change that touches the matcher or the watchlist,
`deploy/redeploy.sh` runs the dry run and asks before applying. By hand:

```bash
docker compose exec trackaroo python seed.py
docker compose exec trackaroo python repair_listings.py            # dry run — review the output
docker compose exec trackaroo python repair_listings.py --apply    # backs up the DB first
```

### Backups

Every real run ends with `backup_db.backup_database()`, which runs whatever
happened before it in the run:

- **Consistent copy:** the SQLite online-backup API, safe while the pipeline writes.
- **Verified:** `PRAGMA quick_check` on the new file. A failure alerts ("Database
  backup problem") and prunes nothing, so a corrupt DB cannot rotate the good
  backups out.
- **Retention by age:** the newest backup of each of the last
  `TRACKAROO_BACKUP_KEEP` days (default 14), plus the 3 newest overall.
- **Optional off-host copy:** set `TRACKAROO_BACKUP_MIRROR_DIR` to a mounted NAS
  path and every backup is also copied there, verified and pruned the same way.
  It is unset by default. To switch it on: mount the share on the host, copy
  `docker-compose.override.example.yml` to `docker-compose.override.yml` with
  the host path on the left, set `TRACKAROO_BACKUP_MIRROR_DIR=/mnt/trackaroo-mirror`
  in `.env`, and redeploy. A mirror failure alerts
  but keeps the local backup.
  **The operator must create/mount that directory before pointing
  `TRACKAROO_BACKUP_MIRROR_DIR` at it — Trackaroo never creates it.** An
  unmounted NAS mount point looks to the filesystem like an ordinary empty
  local directory, so auto-creating it would let the "off-host" copy land
  silently on local disk. A recommended pattern: drop a sentinel file (e.g.
  `.mirror-mounted`) at the top of the real mount once, and check for it in
  your mount unit / health monitoring — a missing sentinel means the mount
  isn't there, well before Trackaroo would have noticed.
- **Health:** `check_backups` warns when the newest backup is older than
  `TRACKAROO_BACKUP_MAX_AGE_HOURS` (default 36).

`data/*.json` (the rebuild source) is not mirrored by this. Back up the project
directory (`db/`, `data/`) at the host level too.

**Restore drill (monthly):**

```bash
python restore_drill.py        # docker: docker exec trackaroo python restore_drill.py
```

It restores the newest backup to a temp file, runs `quick_check`, checks the
tables are non-empty, and checks the live DB has at least as many snapshots on
every day the backup holds. It exits 0 on pass. It never writes to the live DB.

**Restoring for real:**

1. `docker stop trackaroo`. The web app caches its DB connection, so a file
   swap under a running container is not seen until restart.
2. `cp db/trackaroo.db db/trackaroo.db.before-restore`, then
   `cp db/backups/trackaroo_<stamp>.db db/trackaroo.db`, then
   `rm -f db/trackaroo.db-wal db/trackaroo.db-shm`.
3. `docker start trackaroo`. The boot catch-up (`--pending-only`) re-scrapes
   anything today is missing. Older gaps can be re-ingested from `data/*.json`
   with `python ingest.py --date YYYY-MM-DD`.

---

## Option B — Host scheduler (native, no Docker)

No Docker required — run the pipeline directly with the system crontab. The
scripts resolve all paths against the repo root (`config.py` uses its own
location), so this works from any working directory.

```cron
# /etc/cron.d/trackaroo   (or: crontab -e)
# Run every day at 06:30. The pipeline scrapes, ingests, health-checks,
# and keeps the 14 most recent DB backups.
30 6 * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py >> /var/log/trackaroo_daily.log 2>&1
```

**Hourly per-retailer retry (#8), the way the Docker entrypoints do it.** The
Docker image doesn't call plain `run_daily.py` on a fixed schedule like the
one-liner above — it calls `run_daily.py --scheduled` every hour from
`RUN_AT_HOUR` through `RETRY_UNTIL_HOUR` (defaults `4` and `9`; see
[Retry until a cutoff](#retry-until-a-cutoff)). `--scheduled` is a no-op
outside that window, and once every retailer has a complete run for today, so
it is safe to call unconditionally every hour rather than only once. The
native-cron equivalent, using the actual config defaults:

```cron
# Hourly from RUN_AT_HOUR (04:00) through RETRY_UNTIL_HOUR (09:00): the 04:00
# call is the full run, later calls retry only whatever is still pending, and
# a call after everything for today is complete is a no-op.
0 4-9 * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py --scheduled >> /var/log/trackaroo_daily.log 2>&1

# Staleness check at STALENESS_CHECK_HOUR (10:00), after the last retry --
# keep it scheduled AFTER the retry window's end, with at least an hour of
# gap (see "Scheduling it" under Staleness monitor below).
0 10 * * * cd /opt/trackaroo && /usr/bin/env python3 check_staleness.py >> /var/log/trackaroo_staleness.log 2>&1
```

If `RUN_AT_HOUR`/`RETRY_UNTIL_HOUR` are overridden from their defaults, update
the `4-9` range (and the `0 10` staleness line) to match.

### Weekly spec sync (separate, best-effort)

`sync_specs.py` refreshes the `specs` table from the external GPU/Intel/AMD
datasets. It is a wholly separate job — never called from or by `run_daily.py`
— and is best-effort: a failed sync leaves the last-known-good spec data in
place and the site keeps working. Schedule it well clear of the daily price
run (e.g. Sunday 03:00).

**Option C (single image) schedules it automatically.** The all-in-one
entrypoint runs `sync_specs.py` once a week in-container at `SPEC_SYNC_DOW` @
`SPEC_SYNC_HOUR` (default Sunday 03:00), so no host crontab is needed. Tune it
with `-e SPEC_SYNC_DOW=1 -e SPEC_SYNC_HOUR=12` (or set them in the container
env).

For a native (Option B) deployment, add a host crontab entry:

```cron
0 3 * * 0 cd /opt/trackaroo && /usr/bin/env python3 sync_specs.py >> /var/log/trackaroo_specs.log 2>&1
```

A non-zero exit means a source fetch failed (nothing was written); the report
from the last run is in `data/spec_sync_report.json` (`python sync_specs.py
--report-only` reprints it). With the container running you can also trigger
it from a host crontab with `docker exec trackaroo python sync_specs.py` — the
spec state lives in the mapped `db/`, so the outcome is identical to a
host-run sync.

### PCCG scheduled retry (automatic, safe to run unconditionally)

PCCG rate-limits aggressively; when it does, the scraper now fails fast via a
circuit breaker (see docs/archive/IMPROVEMENT_16_Aug_V1.md §10). Because each
run is cheap and respects the cooldown file, the hourly `run_daily.py
--scheduled` retry (see [Retry until a cutoff](#retry-until-a-cutoff) below)
already covers PCCG without any extra guard logic or a separate `--pccg`
cron line — a pending PCCG retry either picks up the missing data or exits
quietly on an active cooldown:

```cron
# Native equivalent of the container scheduler: hourly, run_daily decides.
0 * * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py --scheduled >> logs/cron.log 2>&1
```

Key behaviours that make this safe:

- **Cooldown:** when the circuit breaker trips, the scraper writes
  `data/pccg_cooldown.json`. Any run within the next
  `TRACKAROO_PCCG_COOLDOWN_HOURS` (default 4) skips scraping entirely and
  exits `3` (expected handled behaviour, not a failure — see the scraper
  exit codes under [Health / operational checks](#health--operational-checks)). A successful
  scrape clears the file.
- **Idempotent ingestion:** re-ingesting an already-present snapshot is a
  no-op (existing "never delete, ingestion is idempotent" rule), so retries
  that do succeed never duplicate data.
- **Visibility:** `health_checks.py` reports per-retailer whether today's date
  has a snapshot (`Today Coverage` section), so a blocked PCCG shows up as a
  named warning — `pccg: no snapshot for today (...) yet - scraper cooldown
  active, expected` — even when the retry respected the cooldown and exited
  quietly. Without an active cooldown to explain the gap, the same check
  reports an ERROR instead (`pccg: no snapshot for today (...)`) and pages —
  see the [Staleness monitor](#staleness-monitor--catching-the-run-that-never-happened) section.

> **First run:** the pipeline scrapes live retailer sites, so the dashboard
> populates over the first minutes.

Environment: the scrapers need **no keys** — Scorptec is plain HTML scraping
and PCCG uses its own public read-only Algolia key baked in as the default
(`scraper/pccg.py`; `ALGOLIA_APP_ID` / `ALGOLIA_API_KEY` are optional
overrides only). Set any `TRACKAROO_*` overrides (and the Discord webhook
vars, see "Daily Discord digest") in the crontab's environment or a `.env`
read by the shell wrapper (the scripts read `os.environ` directly — they do
not load a `.env` file themselves; `notify_discord.py` is the exception and
loads one).

To run a scrape manually (from anywhere):

```bash
cd /opt/trackaroo && python run_daily.py
python backup_db.py          # standalone backup, keeps 14
python backup_db.py --keep 30 --backup-dir /mnt/nas/trackaroo
```

**A manual single-retailer run (e.g. `run_daily.py --scorptec`) pages for the
others.** `check_today_coverage` treats every *other* active retailer as
missing today until its own run happens, and that is now an ERROR (not a
warning) unless a PCCG cooldown explains it — so an ad-hoc `--scorptec` run
before the day's scheduled run alerts on PCCG/Umart too. Add `--no-notify` to ingest and run health checks normally (so you can still
see the result in the log) without sending that alert or the digest, or
`--no-health` to skip the checks entirely. `--dry-run` also never alerts
(`alerts_enabled`/`notify_enabled` both treat it as silent), but it still
scrapes and saves JSON to `data/` — it only skips writing to the DB.

### PCCG key rotation

PCC's search runs on Algolia with a public, search-only key that the site
embeds in every page. If PCC rotates it, the scraper **recovers by itself**
(#11b): on a 401/403 it fetches one pccasegear.com category page, reads the
key from the Algolia Insights `aa('init', {appId: ..., apiKey: ...})` block,
caches it in `data/pccg_algolia.json`, and retries that category once. The run
log and the run report say `PCCG Algolia key rotated`. Later runs start from the
cached key, so nothing needs doing.

It still alerts, with no cooldown written, when recovery cannot work:

- the page could not be fetched or carries no key;
- the page still shows the rejected key (PCC may be mid-rotation; the next
  hourly retry tries again);
- the discovered key is rejected too.

Symptom then: a Discord alert "Scraper **PCCG** was refused by the retailer
(credentials rejected) ... update ALGOLIA_API_KEY", and `logs/trackaroo-*.log`
shows `Algolia auth rejected (403)`. Fix it by hand:

1. Open <https://www.pccasegear.com> in a browser, open DevTools -> Network,
   filter on `algolia`, and search the site for anything.
2. Click a `queries` request. Its request headers carry
   `x-algolia-application-id` and `x-algolia-api-key`.
3. Put both in `.env`: `ALGOLIA_APP_ID=...` and `ALGOLIA_API_KEY=...`.
4. Restart the container (`docker restart trackaroo`), or wait: the next
   hourly retry before `RETRY_UNTIL_HOUR` picks the new key up.
5. Update the defaults in `scraper/pccg.py` in a PR, then comment the two
   lines in `.env` out again. An `ALGOLIA_API_KEY` in `.env` beats the cached
   key, so a stale one there costs a rejected query and a page fetch every run
   (the log says so).

---

## Dashboard-only deployment

If you only need the dashboard (pipeline runs elsewhere), the all-in-one image
still works — point it at an existing DB and use the web-only entrypoint so no
pipeline ever runs:

```bash
docker build -t trackaroo .
docker run -d --name trackaroo-web \
  -p 3000:3000 \
  -v /opt/trackaroo/db:/app/db \
  -v /opt/trackaroo/data:/app/data \
  -e TRACKAROO_DB=/app/db/trackaroo.db \
  --entrypoint /usr/bin/tini \
  trackaroo -- node web/server.js
```

### Option B (adapter-node directly)

```bash
cd web && npm ci && npm run build
TRACKAROO_DB=../db/trackaroo.db PORT=3000 HOST=0.0.0.0 node server.js
```

Put this behind a reverse proxy (Caddy / nginx / Traefik) for TLS if the host
is internet-facing.

**Form POSTs and the origin check.** adapter-node checks every form POST (the
product-page price alerts, Discover's Track / Ignore / Retire / Keep) against the
origin it thinks it is serving, and on its own it assumes **https**. Over plain
http that made every form fail with `403 Cross-site POST form submissions are
forbidden` (fixed 6-Oct-2026): `web/server.js` now stamps the real protocol
(`http`) on each request and points adapter-node at it, so the LAN deploy needs
nothing set, whichever hostname or IP you browse with. CI's production-server
smoke test pins this (a same-origin POST must get past the check, a cross-site
one must still get 403).

**Behind a reverse proxy, set `ORIGIN`** to the public URL, e.g.
`ORIGIN=https://trackaroo.example.com`, in `.env` (compose) or the environment
above, or set `PROTOCOL_HEADER=x-forwarded-proto` and `HOST_HEADER=x-forwarded-host`
if the proxy sends those. Either one turns the wrapper's default off.

---

## Health / operational checks

- Heartbeat (#9): set `TRACKAROO_HEARTBEAT_URL` in `.env` (e.g. a
  healthchecks.io check with a 1-day period and a grace that ends after
  `RETRY_UNTIL_HOUR`) and redeploy. It is pinged only after a day where every
  active retailer completed, so a missed ping means a missing or partial day.

- Dashboard health endpoint: `GET /healthz` returns
  `{"ok": true, "version": "<git sha>", "retailers": [...]}` (503 when the DB
  cannot be opened). The image's `HEALTHCHECK` polls it, so `docker ps` shows
  `healthy`. Freshness is in the body but never makes it unhealthy.
- External heartbeat (off until Phase 6): create a check at healthchecks.io
  (free tier) or an Uptime Kuma "push" monitor with a ~26h grace period, and
  set `TRACKAROO_HEARTBEAT_URL` to its ping URL in `.env`. `run_daily.py`
  pings it only after a run that leaves every active retailer complete for the
  day, so a stopped container, a dead host and a partial day all alert.
- Build stamp: `docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t trackaroo .`
- Pipeline health: `run_daily.py` exits `0` when the run was clean (a PCCG
  cooldown skip counts as clean), `1` when nothing could be scraped or the run
  crashed, and `2` when some scraper or health check failed or the backup had
  a problem. Good data is still kept and backed up. Scrapers exit `0` ok,
  `2` incomplete, `3` skipped (cooldown), `4` credentials rejected. Every run
  also writes one `scrape_runs` row per retailer, and the homepage health strip
  shows its time.
- Backups: verify `db/backups/` contains recent files:
  `ls -la db/backups | head`.
- JSON backup integrity: `python export_snapshots.py --repair --dry-run` should
  report 0 snapshots recovered. Anything else means `data/*.json` can no longer
  rebuild the DB — run it without `--dry-run` to fix.
- Missed days: `check_missing_days` runs as part of `run_daily.py` and raises a
  Discord pipeline alert on any calendar gap.

## Daily Discord digest

`run_daily.py` posts a short digest of the biggest CPU/GPU price moves to
Discord after a successful run — but **only when no health check errored**.
A partial or unchecked scrape never celebrates moves that may be artifacts.
`--no-notify` opts out; dry runs, `--scrape-only`, and `--no-health` skip it
automatically.

Set up a webhook in Discord (Server Settings → Integrations → Webhooks → New
Webhook, copy the URL) and pass it to the pipeline. Both CPU and GPU moves
go to the same webhook:

- Option A (Docker): `--env-file .env` (recommended — keeps the secret out of
  your shell history and `docker inspect`), or `-e DISCORD_WEBHOOK_URL=…`.
- Option B (native): put the var in a repo-root `.env` (gitignored) —
  `notify_discord.py` loads it automatically — or export it in the crontab:
  ```cron
  30 6 * * * cd /opt/trackaroo && /usr/bin/env DISCORD_WEBHOOK_URL=... python3 run_daily.py >> /var/log/trackaroo_daily.log 2>&1
  ```

The webhook is optional — with it unset the digest is a no-op, and a
webhook failure is logged without failing the run. Embed colours match the
dashboard tokens (`#F87171` up / `#34D399` down); the per-product link goes to
the retailer listing. `TRACKAROO_PUBLIC_BASE_URL` (optional) additionally
adds a "Trackaroo page" link when the dashboard has a stable public URL.

Preview or verify without sending:

```bash
python notify_discord.py --dry-run   # print the exact embeds
python notify_discord.py --test      # send one static sample embed per webhook
```

## Price alerts

`run_daily.py` also evaluates the user-set **price-drop & restock alerts**
(after a successful run, with the same clean-run gating as the digest).
`check_alerts.py` checks each `price_alerts` row against the two latest
snapshots per listing: a price-drop alert fires when the cheapest in-stock
price is ≤ the target **and** strictly below the last-notified price (a
sustained breach doesn't spam; a further drop re-fires); a restock alert fires
on an out→in transition with a 24h cooldown. Price takes precedence in the
same run; cooldown columns advance only after a successful delivery.

Delivery is stdlib-only and best-effort (never raises — a failure is logged,
never fails the run), per the alert's `channel`:

- `discord` → `TRACKAROO_DISCORD_WEBHOOK_URL`
- `email` → `TRACKAROO_SMTP_HOST/PORT/USERNAME/PASSWORD/FROM/TO`
- `webhook` → `TRACKAROO_ALERT_WEBHOOK_URL` (generic JSON POST)

These are deliberately distinct from the digest's `DISCORD_WEBHOOK_URL` var.
Pass them the same way as the digest (`--env-file .env` for the container, a
repo-root `.env` or the crontab env for a native run).
All are optional — with none set, alert delivery is a no-op.

Preview without sending:

```bash
python check_alerts.py --dry-run   # print what would fire
```

## Delisted-listing check

`run_daily.py` also runs the **delisted-listing check** after a successful
Scorptec scrape (best-effort — a failure never breaks the run). Because the
Scorptec scraper only reads category-grid pages, a delisted product vanishes
from the grid and its last `in_stock` snapshot stays the latest forever.
`check_delisted.py` re-fetches the product page of every active, tracked
Scorptec listing that produced no snapshot for today and marks it `delisted`
only on a positive signal — a 404/410 response or the site's "No Longer
Available" marker. A fetch failure or unrecognised page is left untouched, so
a transient network issue can never delist a live product. The dashboard then
shows a "Delisted" badge instead of a price + stock badge and excludes the
stale price from the group price range.

Tuning (both optional, see `.env.example`):

- `TRACKAROO_SCORPTEC_DELIST_CHECK_MAX` — per-run fetch cap (default 100)
- `TRACKAROO_SCORPTEC_DELIST_PAGE_DELAY` — inter-fetch delay in seconds
  (default 1.5 — a burst of product-page requests gets CDN-throttled)

Preview without writing:

```bash
python check_delisted.py --dry-run   # print what would be marked
```

## Staleness monitor — catching the run that never happened

Every other health check runs *inside* `run_daily.py`, so none of them can fire
when the pipeline does not run at all. That is a real gap, not a theoretical
one: on 27-Aug-2026 the daily run simply had not happened and a human noticed
before the system did.

`check_staleness.py` closes it. It reads only the database — no scraping, no
network, no writes — so it is safe to run on any schedule, independently of the
pipeline it watches.

```bash
python check_staleness.py              # exit 0 = fresh, exit 1 = stale
python check_staleness.py --dry-run    # print the alert instead of posting
python check_staleness.py --threshold-days 2
```

Severity is split deliberately (updated 29-Sep-2026, #8):

| Condition | Status | Effect |
|---|---|---|
| DB missing, unreadable, or empty | ERROR | exit 1 + Discord alert |
| No data today at all | ERROR | exit 1 + Discord alert |
| Any active retailer with nothing today, or never reported | ERROR | exit 1 + Discord alert |
| PCCG missing today while its cooldown is active | WARNING | logged only |

Default threshold is **0 days**. The monitor runs at `STALENESS_CHECK_HOUR`
(10), after the last retry at `RETRY_UNTIL_HOUR` (9), so by then a missing
day is an outage and it alerts that same morning (#8).

**Alerts need `DISCORD_WEBHOOK_ALERT` set** (see `.env.example`). Without it the
monitor still works, but signals only through its exit code — which is enough
for a scheduler, cron `MAILTO`, or an uptime checker.

### Scheduling it

`deploy/entrypoint-single.sh` runs it **once a day at `STALENESS_CHECK_HOUR`**
(default `10`), in its own hourly-poll loop alongside the weekly spec sync. The
hour must sit *after* `RETRY_UNTIL_HOUR` (default `09`) — checking before the
last hourly retry has had its chance would report every morning as an outage.

**The retry loop does not tick exactly on the hour.** `sleep 3600` between
iterations means each `--scheduled` call lands at (container boot time, or the
previous run's finish time) + one hour, drifting by however long the pipeline
itself took to run — it is not anchored to wall-clock `:00`. In practice a
`RETRY_UNTIL_HOUR` retry still normally finishes well before
`STALENESS_CHECK_HOUR`, because one scraper run takes well under an hour, but
the two are not guaranteed to be an hour apart on the wall clock. Keep **at
least a full hour** of gap between `RETRY_UNTIL_HOUR` and
`STALENESS_CHECK_HOUR` (the default `9` vs `10` already does this) — a smaller
gap risks a late-starting retry still being in flight when the staleness check
fires, which the check would report as an outage (see the known gap below)
rather than "still running".

**Known gap (documented, not fixed by this task):** `scrape_runs` only gets a
row once a scraper run *finishes* (`run_daily.record_outcomes`, after the
whole batch for that invocation completes) — there is no "started, not yet
finished" row written at scrape start. If a retry were ever still running when
`STALENESS_CHECK_HOUR` fires (a genuinely hung scraper, or too small a gap
between the two hours), `check_staleness.py` has no way to see "in progress"
and would report that retailer as an outage rather than "still running".
Making the staleness check distinguish those two cases would require writing a
row at scrape start and updating it at finish — a real change to
`run_scraper`'s write pattern, not a small one — so it is left as a known
limitation rather than implemented here. If this ever bites in practice,
prefer widening the gap (lower `RETRY_UNTIL_HOUR` or raise
`STALENESS_CHECK_HOUR`) over racing the two closer together.

Running natively instead? Add it to cron, well clear of the pipeline:

```cron
# Staleness check at 10:00, one hour after the last 09:00 retry.
0 10 * * * cd /opt/trackaroo && /usr/bin/python3 check_staleness.py >> logs/staleness.log 2>&1
```

### Retry until a cutoff

The daily pipeline no longer runs just once. `deploy/entrypoint-single.sh` and
`deploy/entrypoint.sh` call `python run_daily.py --scheduled` every hour;
`run_daily.py` itself decides what to do (`run_daily.in_retry_window`,
`pending_retailers`):

- Outside `RUN_AT_HOUR..RETRY_UNTIL_HOUR` (default `04:00`–`09:59`), `--scheduled`
  is a no-op.
- Inside the window, only retailers whose latest `scrape_runs` row for today is
  **not** `ok` (or that have no row and no snapshot yet — the deploy-day case)
  are scraped. A retailer that already succeeded today is left alone.
- A boot catch-up runs `--pending-only` once immediately (no window check), so
  a container that was down over `RUN_AT_HOUR` does not lose the day.

This means a retailer that fails at `04:00` gets retried at `05:00`, `06:00`,
… up to and including `RETRY_UNTIL_HOUR` — and because `RETRY_UNTIL_HOUR`
(default `9`) is before `STALENESS_CHECK_HOUR` (default `10`), a retailer that
eventually succeeds during a retry still shows up as fresh at the `10:00`
check, instead of waiting for the alert the next day. The Discord digest and
any pipeline alert are each sent at most once per day (`run_daily.claim_once`)
so the hourly retries do not spam Discord.

## Config reference

Every knob is overridable via environment — see `config.py` and `.env.example`
for the full list (paths, health-check thresholds, scraper tuning). The web
frontend honours `TRACKAROO_DB` identically.

### Environment variables added in Phase 3 (29-Sep-2026)

| Variable | Default | What it does | Switched on |
|---|---|---|---|
| `RETRY_UNTIL_HOUR` | `9` | Last local hour a failed/incomplete retailer is retried (hourly from `RUN_AT_HOUR`) | now |
| `SKIP_PIPELINE` | `0` | `1` = dashboard only: no catch-up, no scheduler, never scrapes | CI only |
| `TRACKAROO_MATCH_DROP_RATIO` | `0.6` | ERROR when today's listings per retailer/category fall below this fraction of the trailing median | now |
| `TRACKAROO_MATCH_DROP_WINDOW_DAYS` | `7` | Trailing window for that median | now |
| `TRACKAROO_MATCH_DROP_MIN_HISTORY` | `3` | Prior days needed before the drop rule judges | now |
| `TRACKAROO_BACKUP_KEEP` | `14` | Now **days** (newest backup per day) plus the 3 newest, not a file count | now |
| `TRACKAROO_BACKUP_MAX_AGE_HOURS` | `36` | `check_backups` warns past this age | now |
| `TRACKAROO_BACKUP_MIRROR_DIR` | unset (off) | Verified off-host copy of every backup (a NAS mount) | Phase 6 |
| `TRACKAROO_HEARTBEAT_URL` | unset (off) | GET after a complete, clean day (healthchecks.io / Uptime Kuma push) | Phase 6 |
| `GIT_SHA` (build arg) | `dev` | Baked in as `TRACKAROO_VERSION`, shown by `/healthz` | Phase 6 redeploy script |
| `TRACKAROO_RUN_REPORT` | set by `run_daily` | Internal: where a scraper writes its per-category counts. Never set it yourself. | internal |
| `ALGOLIA_APP_ID` / `ALGOLIA_API_KEY` | code default, then `data/pccg_algolia.json` | Now commented out in `.env.example`; a rotated key is discovered and cached automatically (#11b); set only per "PCCG key rotation" | on rotation |
| `TRACKAROO_SYNTHETIC` | `0` | Set by CI (`.github/workflows/ci.yml`) to skip frontend tests that need real-scrape price/retailer variety a synthetic fixture doesn't have | CI/test only |
