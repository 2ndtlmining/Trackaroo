# Next session (from 5-Oct-2026): plan

Written at the end of 4-Oct-2026. Work top to bottom. Each item says who acts (owner or Claude), how
big it is, and what "done" means. Code items follow the usual flow: brainstorm (bounded or
architectural), then TDD, then the four-suite gate (`python -m pytest -q`; from `web/`: `npm run check`,
`npm test`, `npm run test:e2e`), a CHANGELOG `## Unreleased` line, and a PR. Tell the owner to wait for
**all three** CI jobs to be green before merging (#71 and #72 were merged on a red web job).

## State at the end of 4-Oct

- **main** has v0.7.0 (tag `v0.7.0` at 57b2ad9): Head to head matchups (#60), ops hygiene (#69), file
  splits (#68).
- **Prod** (`giel@dockerhost:~/docker/Trackaroo`, http://192.168.10.163:3000) runs d622f3e. That is the
  matchups code, but `/healthz` still reports release 0.6.1, because 0.7.0 was cut after the deploy.
- **Prod checkout is dirty.** `release.py` was run on the host by mistake, which edited
  `CHANGELOG.md`, `web/package.json` and `web/package-lock.json`. `deploy/redeploy.sh` refuses to run
  until those edits are discarded.
- **PR #73** (open) fixes the red web CI on main. It is test-only: the matchup loader test now seeds
  its own pair, because CI has no `data/`.

## 0. Housekeeping (owner, ~10 min, outside 04:00-09:59)

1. Merge **#73** once all three CI jobs are green. Main CI should then be green again.
2. On dockerhost:
   ```
   cd ~/docker/Trackaroo
   git status --short          # expect only the 3 files above; paste anything else to Claude first
   git checkout -- CHANGELOG.md web/package.json web/package-lock.json
   deploy/redeploy.sh
   ```
   `release.py` is a repo step done on the PC through a PR. The host only pulls and redeploys.
3. Claude then checks from the PC: `curl http://192.168.10.163:3000/healthz` reports release
   **0.7.0**, the footer shows v0.7.0, `/changelog` lists 0.7.0, and a product page shows Head to head.
4. After **9-Oct**: `docker rm trackaroo-old` and `docker rmi trackaroo:pre-compose`. The archive is
   kept on the PC at `Downloads/trackaroo-pre-compose-2026-10-02.tgz`.

## 1. Issue hygiene pass (Claude, S)

Several issues from the 23-Sep review look fixed by the 28-Sep..4-Oct work but are still open:
#2, #21, #23, #27, #29 and the #40 tracker. Check each one against live prod and the code, then
either close it with a comment naming the PR, or comment with exactly what is left. Do not close
anything without evidence. Update #40's checklist to match.

## 2. #70: one price rule for the product headline (Claude, S, bounded)

The headline price (`web/src/lib/productHeadline.ts` via `toListingDisplays`) skips listings unseen
for more than 7 days but **includes bundles**. The #59 rule (`cheapestInStockLatest`) **excludes
bundles** but includes active listings not seen recently. The Head to head panel now shows both
numbers on one page.

- Decision for the owner (one question): should the shared rule be "#59 plus the 7-day staleness
  guard" everywhere (recommended), or should only the headline change?
- Done when every surface agrees and a cross-surface test like `value.test.ts`'s "one price rule"
  cases pins it.

## 3. #15 remainder: ops hygiene (Claude, S-M)

Already done (#69): the dead Algolia knobs, scoped alert deletes, and the target price cap.
Remaining:

1. **run_daily lock file.** Two runs must never overlap: the scheduler, a `--pending-only` boot
   catch-up and a manual run can collide. Use an OS-level lock (e.g. `fcntl.flock` on Linux, with a
   portable fallback) held for the whole run. A second run logs "already running" and exits with a
   distinct code that `run_daily --scheduled` treats as not-a-failure. Tests: a second process
   gets the lock-held exit; the lock is released after a crash.
2. **requirements-dev.txt + pinned dependencies.** Split the test-only packages out of
   `requirements.txt`. Pin exact versions with hashes (`pip-compile --generate-hashes` or
   equivalent). Update the Dockerfile and CI to install from the pinned files. Done when the image
   builds and the CI backend job is green.
3. **Docs:** the Docker Desktop WAL caveat (DEPLOYMENT.md), and an ORIGIN note for a future reverse
   proxy.
4. Close #15.

## 4. #20 items 2-3: watchlist maintainability (Claude, M, needs one owner decision)

1. **Aliases.** Only `search_terms[0]` is ever read; about 200 secondary aliases do nothing. Owner
   decision: (a) matchers try every alias, or (b) drop the alias column in favour of the chip key
   plus an optional `extra_keys` column. Either way, fix the CSV header text and ARCHITECTURE §7.
2. **Spec pipeline for the next generations:**
   - an amd.com series path in config (`Ryzen 7 10700X` must resolve);
   - configurable Intel CSV URLs;
   - `pending_specs` for products added within 7 days;
   - MSRP added in the same place a product is added.
3. Close #20.

## 5. #11: PCCG Algolia key rotation (Claude, M, robustness)

If PCCG rotates its public Algolia key, PCCG scraping stops for good and nothing loud happens. Read
the issue's proposal first. The likely shape is: detect auth rejection (exit 4 already exists), alert
once, and try re-reading the key from the PCCG site before giving up. Must keep the 2-query budget
(`test_pccg_query_budget.py`).

## 6. Waiting on the owner (no code until then)

- **#9 heartbeat:** a healthchecks.io (or Uptime Kuma push) URL to set as `TRACKAROO_HEARTBEAT_URL`
  in the host `.env`. Then one redeploy, and stop the container briefly to confirm the alert fires.
- **#10 backups:** an off-host mount (NAS) for `TRACKAROO_BACKUP_MIRROR_DIR`. The directory must
  already exist. Then confirm a mirrored copy appears after the next run.
- **#58 CPU perf coverage:** blocked on published data (15 of 38 current and previous generation).
- **Discover → Track:** nothing is in Requested today. When the owner clicks Track on parts, Claude
  turns the Requested rows into a `db/watchlist.csv` PR (fill in `?c`/`?GB` from spec pages).

## 7. Bigger backlog (owner to prioritise; each needs a brainstorm)

#17 generations config, #18 retirement status column, #19 `manage_watchlist.py` CLI, #35 small
feature ideas, #36/#37 retailers four and five (PLE, Computer Alliance), #39 shared scraper toolkit.
