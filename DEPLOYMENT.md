# Trackaroo Deployment

Self-hosted deployment options for the daily tracker + dashboard. Two service
types:

- **`cron`** — the Python pipeline: scrape both retailers → validate JSON →
  ingest → health-check DB → optional DB backup. Runs on a fixed interval.
- **`web`** — the SvelteKit dashboard (adapter-node, port 3000).

The simplest deployment is a **single all-in-one Docker image** that runs both
(Option C). A two-container split with docker-compose (Option A) is kept for
users who prefer separate services. Both share one volume containing the SQLite
DB (`/data/trackaroo.db`), the scraped JSON snapshots (`/data/`), and the
backups. WAL mode (enabled by the writers) makes the concurrent writer/reader
safe.

---

## Option C — Single Docker image (recommended)

One container serves the dashboard **and** runs the daily pipeline. No
docker-compose needed.

```bash
docker build -t trackaroo .
docker run -d --name trackaroo \
  -p 3000:3000 \
  -v trackaroo-data:/data \
  trackaroo
```

On boot the container:
1. Creates + seeds the SQLite DB (`python seed.py`) if missing.
2. Hydrates a fresh DB from the snapshot history baked into the image
   (`deploy/bootstrap-data.sh`) so the dashboard isn't empty on first boot —
   a no-op when the volume already has snapshots.
3. Starts the SvelteKit dashboard on :3000.
4. Runs the daily pipeline immediately, then every `RUN_INTERVAL_HOURS`.
5. Runs the spec sync (`python sync_specs.py`) once a week at
   `SPEC_SYNC_DOW` @ `SPEC_SYNC_HOUR` (default Sunday 03:00), clear of the
   daily price run. It refreshes the `specs` table (GPU/CPU) from upstream
   sources; safe to re-run (upserts).

Logs: `docker logs -f trackaroo`

| Setting | Default | Override |
|---|---|---|
| Pipeline cadence | 24h | `-e RUN_INTERVAL_HOURS=6` |
| Backups retained | 14 | `-e BACKUP_KEEP=30` |
| Dashboard port | 3000 | `-p 8080:3000` |
| Spec-sync day | Sunday (0) | `-e SPEC_SYNC_DOW=1` (Mon) … `6` (Sat) |
| Spec-sync hour | 03:00 | `-e SPEC_SYNC_HOUR=12` |

One-shot run (e.g. from a host crontab, starts web then exits after a pipeline):

```bash
docker run --rm -v trackaroo-data:/data -e RUN_ONCE=1 trackaroo
```

> **First run:** the pipeline scrapes live retailer sites, so the dashboard
> populates over the first minutes. `seed.py` pre-populates the product
> watchlist so pages render even before the first scrape completes.

---

## Option A — Docker Compose (two services)

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f cron web
```

Both services build from the **same repo-root `Dockerfile`** and pin their
runtime entrypoints in the compose file (`cron` → pipeline loop, `web` →
adapter-node server). Defaults:

| Setting | Default | Override |
|---|---|---|
| Cron cadence | 24h | `RUN_INTERVAL_HOURS=6 docker compose up ...` |
| Backups retained | 14 | `BACKUP_KEEP=30` |
| Dashboard host port | 3000 | `PORT_TRACKAROO=8080` |

The `cron` service runs `run_daily.py --backup $KEEP` every interval via
`deploy/entrypoint.sh`. It is safe to run the same image one-shot from a host
crontab instead (see Option B).

Data lives in the named volume `trackaroo-data` (`/data` in both containers):

```
/data/
├── trackaroo.db        # SQLite DB (WAL)
├── cpu_scorptec_*.json # scraped snapshots (this run + history)
├── gpu_pccg_*.json
└── backups/            # trackaroo_YYYY-MM-DD_HHMMSS.db (retention-pruned)
```

> **First run:** the DB is created empty and seeded the first time ingestion
> runs. To seed from the watchlist first, run the seed step once:
> `docker compose run --rm cron sh -c "python seed.py && python run_daily.py --backup 14"`.

### Volume backup

The Docker volume is just files on the host. For Proxmox, the simplest robust
backup is a nightly `dump` of the volume directory, or use the in-app
`backup_db.py` retention that already writes copies into `/data/backups/`.

---

## Option B — Host cron (Proxmox/Linux)

No Docker required — run the pipeline directly with the system crontab. The
scripts resolve all paths against the repo root (`config.py` uses its own
location), so this works from any working directory.

```cron
# /etc/cron.d/trackaroo   (or: crontab -e)
# Run every day at 06:30. The pipeline scrapes, ingests, health-checks,
# and keeps the 14 most recent DB backups.
30 6 * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py --backup 14 >> /var/log/trackaroo_daily.log 2>&1
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

For bare-host and Option A (compose) deployments, add a host crontab entry:

```cron
0 3 * * 0 cd /opt/trackaroo && /usr/bin/env python3 sync_specs.py >> /var/log/trackaroo_specs.log 2>&1
```

A non-zero exit means a source fetch failed (nothing was written); the report
from the last run is in `data/spec_sync_report.json` (`python sync_specs.py
--report-only` reprints it). For the compose setup you can also run
`docker exec trackaroo python sync_specs.py` from a host crontab — the spec
state lives in the shared volume, so the outcome is identical to a host-run
sync.

### PCCG scheduled retry (automatic, safe to run unconditionally)

PCCG rate-limits aggressively; when it does, the scraper now fails fast via a
circuit breaker (see IMPROVEMENT_16_Aug_V1.md §10). Because each run is cheap
and respects the cooldown file, you can schedule a plain `run_daily.py --pccg`
a few hours after the main daily run without any guard logic — it either picks
up the missing PCCG data or exits quietly:

```cron
30 6 * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py --backup 14 >> /var/log/trackaroo_daily.log 2>&1
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
runs the same image one-shot (`docker run --rm -v trackaroo-data:/data -e RUN_ONCE=1 trackaroo`) — note this runs the full pipeline, so pick a time clear of
the main scheduled run, or run a second container with the pipeline-only
entrypoint (`deploy/entrypoint.sh`). The cooldown file lives in the shared
volume, so the scoring is identical either way.

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
cd /opt/trackaroo && python run_daily.py --backup 14
python backup_db.py          # standalone backup, keeps 14
python backup_db.py --keep 30 --backup-dir /mnt/nas/trackaroo
```

---

## Dashboard-only deployment

If you only need the dashboard (pipeline runs elsewhere), the all-in-one image
still works — set `RUN_INTERVAL_HOURS` high or skip the scheduler:

```bash
docker build -t trackaroo .
docker run -d --name trackaroo-web \
  -p 3000:3000 \
  -v /opt/trackaroo-data:/data \
  -e TRACKAROO_DB=/data/trackaroo.db \
  -e RUN_INTERVAL_HOURS=99999 \
  trackaroo
```

### Option B (adapter-node directly)

```bash
cd web && npm ci && npm run build
TRACKAROO_DB=../db/trackaroo.db PORT=3000 HOST=0.0.0.0 node build/index.js
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
- Backups: verify `/data/backups/` contains recent files:
  `ls -la /data/backups | head`.

## Daily Discord digest

`run_daily.py` posts a short digest of the biggest CPU/GPU price moves to
Discord after a successful run — but **only when no health check errored**.
A partial or unchecked scrape never celebrates moves that may be artifacts.
`--no-notify` opts out; dry runs, `--scrape-only`, and `--no-health` skip it
automatically.

Set up a webhook per channel in Discord (Server Settings → Integrations →
Webhooks → New Webhook, copy the URL) and pass them to the pipeline:

- Option C (single image): `-e DISCORD_WEBHOOK_GPU=… -e DISCORD_WEBHOOK_CPU=…`
- Option A (compose): export the vars on the host or in a `.env`; the cron
  service forwards them (see `docker-compose.yml`).
- Option B (host cron): put the vars in a repo-root `.env` (gitignored) —
  `notify_discord.py` loads it automatically — or export them in the crontab:
  ```cron
  30 6 * * * cd /opt/trackaroo && /usr/bin/env DISCORD_WEBHOOK_GPU=... DISCORD_WEBHOOK_CPU=... python3 run_daily.py --backup 14 >> /var/log/trackaroo_daily.log 2>&1
  ```

Both webhooks are optional — with neither set the digest is a no-op, and a
webhook failure is logged without failing the run. Embed colours match the
dashboard tokens (`#F87171` up / `#34D399` down); the per-product link goes to
the retailer listing. `TRACKAROO_PUBLIC_BASE_URL` (optional) additionally
adds a "Trackaroo page" link when the dashboard has a stable public URL.

Preview or verify without sending:

```bash
python notify_discord.py --dry-run   # print the exact embeds
python notify_discord.py --test      # send one static sample embed per webhook
```

## Config reference

Every knob is overridable via environment — see `config.py` and `.env.example`
for the full list (paths, health-check thresholds, scraper tuning). The web
frontend honours `TRACKAROO_DB` identically.