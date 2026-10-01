# Moving prod on `dockerhost` from `docker run` to docker compose

A step-by-step guide for **this** server. Every command is run on the Ubuntu VM
(`ssh giel@dockerhost`) unless it says **(on the PC)**. Nothing in it deletes
price data: the database and the JSON snapshots are backed up twice, then
**moved**, never recreated.

| | |
|---|---|
| Server | `giel@dockerhost` (Ubuntu), dashboard on port 3000 |
| Project folder | `~/docker/Trackaroo` (holds `db/`, `data/`, `.env`) |
| Running today | container `trackaroo`, image `trackaroo`, started with plain `docker run` |
| Also on the host | `watchtower`, `portainer`, `ergo-monitor` (all untouched by this guide) |
| Code | `https://github.com/2ndtlmining/Trackaroo` (public, branch `main`) |
| Time needed | about 45 minutes, most of it waiting |
| When | **outside 04:00–09:59 Melbourne time** — that is the daily scrape window |

**Before you start:** the three Phase 3/4/6 pull requests are merged into
`main` and CI is green. Keep a terminal on the PC open as well, for the
`scp` copies.

> Stop at any step whose output looks different from what is described, and
> paste it to Claude. Every step up to Step 6 can be undone by simply starting
> the old container again (`docker start trackaroo`).

---

## Step 1 — Look before touching anything (read-only)

```bash
cd ~/docker/Trackaroo
docker compose version
git rev-parse --is-inside-work-tree && git status -sb | head -5 && git log --oneline -1
ls -la
ls -la db
docker inspect trackaroo --format 'image={{.Config.Image}} restart={{.HostConfig.RestartPolicy.Name}}{{println}}{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
docker inspect trackaroo --format '{{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1 | sort
df -h ~
date; TZ=Australia/Melbourne date
```

What you should see, and what it decides:

1. **`docker compose version`** prints `Docker Compose version v2.x`. If it
   says `'compose' is not a docker command`, install the plugin first:
   `sudo apt-get update && sudo apt-get install -y docker-compose-plugin`.
2. **The git line** decides which path you follow in Step 4:
   - it prints `true`, a branch and a commit → **Path A** (the folder is already a git checkout);
   - it prints `fatal: not a git repository` → **Path B** (it is a plain folder).
   If `git status` lists *modified* files (lines starting ` M`), stop and paste them to Claude.
3. **The mounts** should read
   `/home/giel/docker/Trackaroo/db -> /app/db` and
   `/home/giel/docker/Trackaroo/data -> /app/data`.
   If they point anywhere else, stop and paste them: the rest of this guide assumes those two.
4. **The env names** (names only, no values are printed) show which settings
   the old container runs with. Check each one is also in `~/docker/Trackaroo/.env`
   (`cut -d= -f1 .env`). If there is no `.env` file, stop and tell Claude.
5. **`df -h ~`** needs free space of at least twice `du -sh db data`.

## Step 2 — Check `.env` for characters compose reads differently

Compose strips quotes and treats `$` as the start of a variable; `docker run`
did neither.

```bash
grep -n '\$' .env
grep -nE "=[\"']" .env
grep -n '^ALGOLIA_' .env
```

- A `$` inside a value (a password, a webhook URL) must be doubled: `$` → `$$`.
- A value wrapped in quotes loses the quotes. That is usually what you want; check any URL still reads correctly without them.
- `ALGOLIA_APP_ID` / `ALGOLIA_API_KEY` lines should be removed (or commented out) unless you set them on purpose: the code carries the current key, and a stale copy in `.env` overrides it.

Keep a copy of the original first: `cp .env .env.pre-compose`.

## Step 3 — Back up twice, then stop the old container

```bash
cd ~/docker/Trackaroo

# 1. A verified SQLite copy, made by the app while it runs.
docker exec trackaroo python backup_db.py
ls -t db/backups | head -3

# 2. Keep that newest backup OUTSIDE db/backups (which gets pruned):
#    this is the "nothing was lost" reference for Step 7.
cp "db/backups/$(ls -t db/backups | head -1)" db/pre-compose.db
ls -la db/pre-compose.db

# 3. Note the code the old container runs (Path A only; prints nothing on Path B).
git rev-parse HEAD 2>/dev/null | tee ~/trackaroo-old-sha.txt

# 4. Stop it, so nothing writes while the archive is made.
docker stop trackaroo

# 5. A byte-for-byte archive of everything.
tar czf ~/trackaroo-pre-compose-$(date +%F).tgz -C ~/docker/Trackaroo db data .env
ls -la ~/trackaroo-pre-compose-*.tgz
```

**(on the PC)** copy the archive off the server:

```
scp giel@dockerhost:~/trackaroo-pre-compose-*.tgz C:/Users/theun/Downloads/
```

The archive contains `.env`, so treat it like a password file (don't share or
upload it). The dashboard is down from here until Step 6 finishes.

## Step 4 — Keep the old container and image for rollback

```bash
docker rename trackaroo trackaroo-old
docker tag trackaroo:latest trackaroo:pre-compose
docker ps -a --filter name=trackaroo
```

You should see `trackaroo-old` with status `Exited`. Leave it there for a week.
Watchtower ignores stopped containers.

## Step 5 — Get the new code into `~/docker/Trackaroo`

### Path A — the folder is already a git checkout

```bash
cd ~/docker/Trackaroo
git fetch origin
git checkout main
git pull --ff-only
git log --oneline -1
ls docker-compose.yml deploy/redeploy.sh
```

`git status` should now show nothing modified. `db/trackaroo.db`, `db/backups/`,
`data/`, `.env` and `logs/` are ignored by git, so the pull never touches them.

### Path B — the folder is not a git checkout

Clone next to it, move the data across (a move on the same disk is instant and
copies nothing), then swap the two folders:

```bash
cd ~/docker
git clone https://github.com/2ndtlmining/Trackaroo.git Trackaroo-new

# Data only. Never replace the clone's db/ folder: it holds code files
# (schema.sql, watchlist.csv, watchlist.py, launch_msrp.json).
mv Trackaroo/db/trackaroo.db*  Trackaroo-new/db/
mv Trackaroo/db/backups        Trackaroo-new/db/
mv Trackaroo/db/pre-compose.db Trackaroo-new/db/
mv Trackaroo/data              Trackaroo-new/
cp Trackaroo/.env Trackaroo/.env.pre-compose Trackaroo-new/
[ -d Trackaroo/logs ] && mv Trackaroo/logs Trackaroo-new/

# Swap: the old code stays beside it for rollback.
mv Trackaroo Trackaroo-old-files
mv Trackaroo-new Trackaroo

cd ~/docker/Trackaroo
ls db data | head; git status -sb
```

`git status` must show no modified files (the moved data is ignored). The folder
path is the same as before, so nothing else on the host needs to change.

## Step 6 — Build and start with compose

```bash
cd ~/docker/Trackaroo
SKIP_BACKUP=1 deploy/redeploy.sh
```

`SKIP_BACKUP=1` because Step 3 was the backup (there is no running compose
container to take one from yet). What happens, in order:

1. **Checks:** `.env` exists, clean checkout, not in the scrape window, no old-style `trackaroo` container (renamed in Step 4).
2. **`git pull`**, then **build** the image with the commit's SHA (a few minutes the first time).
3. **Start** the container, then wait for it to report *healthy* (usually under a minute).
4. **Wait for the boot catch-up**: it immediately scrapes whatever today is
   still missing. On this first start that includes **Umart**, which the old
   build never scraped, so allow 5–20 minutes. The script prints nothing new
   while it waits; `docker compose logs -f trackaroo` in a second terminal
   shows progress. On first boot the logs also show `migrate.py` adding three
   bookkeeping tables and widening the retailer list; that changes no prices.
5. **Repair dry run**: a list of listings that were filed under the wrong
   product (for example 8GB RTX 5060 Ti cards under the 16GB product), each
   line `old product -> new product  title`. Read it, then answer **`y`**.
   It backs up the DB again first, and moves listings without dropping any price.
6. **Verify**: `/healthz` must report the new build and list `umart`. It ends
   with `[redeploy] done: <sha> is live`.

If it stops with `ERROR`, nothing after that line ran. Paste the output to
Claude; to go back instead, see Rollback below.

## Step 7 — Prove nothing was lost, then look at the site

```bash
cd ~/docker/Trackaroo
docker compose exec trackaroo python restore_drill.py --backup /app/db/pre-compose.db
docker compose ps
docker ps -a --filter name=trackaroo
```

- `restore_drill` must end in a pass (exit 0): the live DB has **at least as
  many price snapshots on every day** as the pre-move backup.
- `docker compose ps` shows `trackaroo` as `running (healthy)`; `trackaroo-old` is still `Exited`.

In a browser, `http://dockerhost:3000` (or the server's IP, e.g. `http://192.168.10.163:3000`):

- The footer ends with **`build <sha>`**, matching `git log --oneline -1`.
- `/products?category=gpu&q=5060%20ti` lists both **GeForce RTX 5060 Ti 16GB** and **GeForce RTX 5060 Ti 8GB**.
- The home page health strip lists **Umart** (and Scorptec, PCCG).
- `/deals` shows nothing under 2% or $10 off.
- The RTX 5090 product page has no listings for other cards.

Hard-refresh (Ctrl+F5) if a page looks old: list pages are cached for a minute.

## Step 8 — Next morning

```bash
cd ~/docker/Trackaroo
docker compose logs --since 12h trackaroo | grep -E 'Starting pipeline|Pipeline finished|ERROR' | tail
ls data | grep "$(TZ=Australia/Melbourne date +%d_%B_%Y)"
```

The 04:00 run should show `Pipeline finished.`, and today's files should
include `*_umart_*.json` next to scorptec and pccg.

## Step 9 — Optional switch-ons (any day after)

**Heartbeat** (an alert if a day's scrape never completes): create a check at
healthchecks.io (period 1 day, grace ending after 10:00 Melbourne), then add to
`.env`:

```
TRACKAROO_HEARTBEAT_URL=https://hc-ping.com/<your-uuid>
```

**Off-host backup copy** (to a NAS already mounted on the VM, e.g. at `/mnt/nas/trackaroo`):

```bash
cd ~/docker/Trackaroo
cp docker-compose.override.example.yml docker-compose.override.yml
nano docker-compose.override.yml     # left-hand path = the NAS folder on the VM
echo 'TRACKAROO_BACKUP_MIRROR_DIR=/mnt/trackaroo-mirror' >> .env
```

The NAS folder must already exist and be mounted: Trackaroo never creates it.
After either change, run `deploy/redeploy.sh` (outside 04:00–09:59).

## Rollback (within the week)

Only needed if the new version misbehaves. The price data stays in place either way.

```bash
cd ~/docker/Trackaroo
docker compose down
```

**Path A:**

```bash
git checkout "$(cat ~/trackaroo-old-sha.txt)"
```

(Before trying the move again later, `git checkout main` first.)

**Path B:** put the data back into the old folder and swap back:

```bash
cd ~/docker
mv Trackaroo/db/trackaroo.db* Trackaroo/db/backups Trackaroo/db/pre-compose.db Trackaroo-old-files/db/
mv Trackaroo/data Trackaroo-old-files/
mv Trackaroo Trackaroo-compose && mv Trackaroo-old-files Trackaroo
```

**Optional, both paths** — also undo the migration and the listing repairs
(prices scraped since the move stay in `data/*.json`):

```bash
cd ~/docker/Trackaroo
cp db/pre-compose.db db/trackaroo.db && rm -f db/trackaroo.db-wal db/trackaroo.db-shm
```

Then start the old container again:

```bash
docker rename trackaroo-old trackaroo && docker start trackaroo
```

## After a week — tidy up

When nothing needed rolling back:

```bash
docker rm trackaroo-old
docker rmi trackaroo:pre-compose
rm -rf ~/docker/Trackaroo-old-files      # Path B only, and only after checking it holds no data
```

Keep `~/trackaroo-pre-compose-*.tgz`, the copy on the PC, and `db/pre-compose.db`.

## From now on — every future update

```bash
cd ~/docker/Trackaroo
deploy/redeploy.sh
```

Outside 04:00–09:59 Melbourne time. It backs up, pulls, builds, restarts,
waits, offers the listing repair and verifies. Logs: `docker compose logs -f trackaroo`.

Portainer shows the container as part of a stack it did not create ("limited"
control). Manage Trackaroo with these commands, not from Portainer's stack editor.
