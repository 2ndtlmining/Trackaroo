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

## Option A — Docker (recommended)

```bash
docker build -t trackaroo .
```

Then run it with the DB and snapshots mapped onto the host, so the data
outlives the container:

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

| Setting | Default | Override |
|---|---|---|
| Daily run hour (local) | `04` | `-e RUN_AT_HOUR=6` |
| Timezone | `Australia/Melbourne` | `-e TZ=Europe/Berlin` |
| Backups retained | 14 | `-e TRACKAROO_BACKUP_KEEP=30` |
| Dashboard host port | 3000 | `-p 8080:3000` |
| Spec-sync day / hour | Sun / 03 | `-e SPEC_SYNC_DOW=1 -e SPEC_SYNC_HOUR=12` |

On boot the container seeds the DB if missing, hydrates a fresh one from the
snapshot history baked into the image (a no-op once snapshots exist), starts
the dashboard, and runs the pipeline immediately **if today has no data yet**.
Every real full run backs up the DB automatically (opt out with `--no-backup`).

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

### Upgrading

```bash
docker stop trackaroo && docker rm trackaroo
docker build -t trackaroo .
# re-run the docker run command above
```

The data is in the mounts, not the container, so this is non-destructive.

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

After pulling a change that touches the matcher or the watchlist:

```bash
docker exec trackaroo python seed.py
docker exec trackaroo python repair_listings.py            # dry run — review the output
docker exec trackaroo python repair_listings.py --apply    # backs up the DB first
```

### Backups

`backup_db.py` writes retention-pruned copies into `db/backups/` on every real
run. Because that is a host directory rather than a Docker volume, any
host-level backup of the project directory picks them up.

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
circuit breaker (see docs/archive/IMPROVEMENT_16_Aug_V1.md §10). Because each run is cheap
and respects the cooldown file, you can schedule a plain `run_daily.py --pccg`
a few hours after the main daily run without any guard logic — it either picks
up the missing PCCG data or exits quietly:

```cron
30 6 * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py >> /var/log/trackaroo_daily.log 2>&1
30 12 * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py --pccg >> /var/log/trackaroo_pccg_retry.log 2>&1
30 18 * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py --pccg >> /var/log/trackaroo_pccg_retry.log 2>&1
```

Key behaviours that make this safe:

- **Cooldown:** when the circuit breaker trips, the scraper writes
  `data/pccg_cooldown.json`. Any run within the next
  `TRACKAROO_PCCG_COOLDOWN_HOURS` (default 4) skips scraping entirely and
  exits `0` (expected handled behaviour, not a failure). A successful scrape
  clears the file.
- **Idempotent ingestion:** re-ingesting an already-present snapshot is a
  no-op (existing "never delete, ingestion is idempotent" rule), so retries
  that do succeed never duplicate data.
- **Visibility:** `health_checks.py` reports per-retailer whether today's date
  has a snapshot (`Today Coverage` section), so a blocked PCCG shows up as a
  named warning — `pccg: no snapshot for today yet` — even when the retry
  respected the cooldown and exited quietly.

For the all-in-one Docker container (Option C), add a host crontab entry that
runs the same image one-shot (`docker run --rm -v "$PWD/db:/app/db" -v "$PWD/data:/app/data" -e RUN_ONCE=1 trackaroo`) — note this runs the full pipeline, so
pick a time clear of the main scheduled run, or run a second container with the
pipeline-only entrypoint (`deploy/entrypoint.sh`). The cooldown file lives in
the shared `data/` directory, so the scoring is identical either way.

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

---

## Health / operational checks

- Dashboard health endpoint: the app serves pages over HTTP; monitor
  `/` returning 200.
- Pipeline health: `run_daily.py` exits non-zero and the daily log contains
  `DB health: all N checks passed` on a good day. `health_checks.py` also runs
  standalone (`--json-only` / `--db-only`).
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

Severity is split deliberately:

| Condition | Status | Effect |
|---|---|---|
| DB missing, unreadable, or empty | ERROR | exit 1 + Discord alert |
| Newest snapshot across **all** retailers older than the threshold | ERROR | exit 1 + Discord alert |
| One retailer lagging while others are current (e.g. PCCG cooldown) | WARNING | logged only — the pipeline is running, data is merely degraded |

Default threshold is **1 day**: a run that has not fired *yet today* is not an
outage, but two days of silence means one was missed.

**Alerts need `DISCORD_WEBHOOK_ALERT` set** (see `.env.example`). Without it the
monitor still works, but signals only through its exit code — which is enough
for a scheduler, cron `MAILTO`, or an uptime checker.

### Scheduling it

`deploy/entrypoint-single.sh` runs it **once a day at `STALENESS_CHECK_HOUR`**
(default `10`), in its own hourly-poll loop alongside the weekly spec sync. The
hour must sit *after* `RUN_AT_HOUR` (default `04`) — checking before the daily
run has had its chance would report every morning as an outage.

Running natively instead? Add it to cron, well clear of the pipeline:

```cron
# Staleness check at 10:00, six hours after the 04:00 pipeline.
0 10 * * * cd /opt/trackaroo && /usr/bin/python3 check_staleness.py >> logs/staleness.log 2>&1
```

## Config reference

Every knob is overridable via environment — see `config.py` and `.env.example`
for the full list (paths, health-check thresholds, scraper tuning). The web
frontend honours `TRACKAROO_DB` identically.