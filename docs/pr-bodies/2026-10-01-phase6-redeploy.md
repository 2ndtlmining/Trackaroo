Phase 6 of the 28-Sep roadmap (`docs/superpowers/plans/2026-09-30-redeploy.md`). Stacked on the UX PR; merge robustness, then UX, then this one.

## What shipped
- **#3 Build stamp** (`2a08dfe`): the footer shows the SHA of the running build, and `/healthz` reports the same `version`.
- **`docker-compose.yml`** (`dc21869`): a single `trackaroo` service. It mounts `db/`, `data/` and `logs/`, rotates Docker logs (the #15 part), passes the `GIT_SHA` build arg, and opts out of watchtower, since this image is built on the host and never pulled. Compose is now the supported way to deploy; the owner reversed the old "no compose" rule on 30-Sep.
- **`deploy/redeploy.sh`** (`e0ac96e`, review fixes in `749586b`): pulls, backs up, builds with the SHA, starts the container, waits for `healthy` and for the boot catch-up to finish, dry-runs the listing repair, and verifies the result. If a step fails, it rolls back to the previous image.
- **Docs** (`1992519`, `9e69774`): DEPLOYMENT.md now covers compose, the redeploy steps and the first migration. There's also a copy-paste migration guide for the prod host at `docs/runbooks/dockerhost-compose-migration.md`.

## Rehearsed against prod data (1-Oct)
Rehearsed on an SQLite backup copy of the live DB: 100 products, 485 listings, 21,058 snapshots, daily from 9 Aug to 30 Sep.
- **Sequence:** `migrate.py`, then `seed.py` (added 6 products), then `repair_listings.py`.
- **Repair:** the dry run proposed 65 moves and all were correct (46 memory-variant splits, 8 wrong-model fixes, 11 non-matches detached). After `--apply`, a second dry run found 0 moves.
- **Nothing lost:** `restore_drill.py` exits 0. Snapshot counts per day are identical, every snapshot row and every listing's ID and SKU is unchanged, and there are 0 orphaned snapshots.
- **Served:** the migrated copy, served by `node server.js`, returns 200 on every main page.

## Gate (clean tree, `07e90ea`)
pytest **1073**, vitest **791**, Playwright **115**, svelte-check **0 errors, 0 warnings**. The image was built offline with `GIT_SHA`, booted `healthy`, and `/healthz` reported `"version":"07e90ea"`.

## After merge
Migrate the prod host by following `docs/runbooks/dockerhost-compose-migration.md`, Path A (the host is a clean git checkout of `main`). Comment out the `ALGOLIA_*` lines in `.env`. Until Umart's first scrape, the home page shows Umart as "missing".

Close issues only after prod has been verified.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
