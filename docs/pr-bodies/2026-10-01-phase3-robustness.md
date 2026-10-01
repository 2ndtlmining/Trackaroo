Phase 3 of the 28-Sep roadmap (`docs/superpowers/plans/2026-09-29-robustness.md`). Stacked PRs: **this one → UX (phase 4) → redeploy (phase 6)**. Merge in that order.

## What shipped
Covers #12, #7, #8, #11a, #14, #13, #9, #10 and risks R1–R4, plus part of #15.

- **Failures can't slip past quietly any more.** A single exception can no longer skip the digest gate, the alerts or the backup, and a run where everything fails now raises an alert. A bad JSON file is skipped and reported instead of crashing the run.
- **Scraper exit codes mean something.** Scrapers exit with 0 (ok), 2 (degraded), 3 (cooldown) or 4 (key rejected). An empty scrape or a rejected PCCG key raises an alert. A cooldown only warns.
- **Retailer health is visible.** Every active retailer appears on the health strip, showing "missing" if it has never reported, along with its last scrape time and matched count.
- **Failed retailers get retried the same morning.** They're retried hourly until `RETRY_UNTIL_HOUR` (09), and the staleness monitor alerts that same morning. Scrapers save after each category, so a timeout keeps whatever finished.
- **Scraper drift is caught earlier.** Adds page and card telemetry, real-HTML fixtures, and rules that flag selector drift and drops against a trailing median.
- **CI** (`.github/workflows/ci.yml`, first run is on this push) runs pytest, vitest, svelte-check, Playwright, a `node server.js` smoke test, and an offline `docker build` plus boot.
- **Health endpoint.** Adds `/healthz`, a Docker HEALTHCHECK and a build stamp.
- **Backups** are checked with `quick_check`, pruned by age, and covered by a restore drill.
- **Built but switched off until phase 6:** `TRACKAROO_HEARTBEAT_URL`, `TRACKAROO_BACKUP_MIRROR_DIR`, and the `GIT_SHA` build arg.

## Deploy notes
- `migrate.py`, which runs at boot, adds the `active_retailers`, `scrape_runs` and `run_markers` tables.
- On deploy day, a retailer that already has today's snapshots is not scraped again.
- `TRACKAROO_BACKUP_KEEP` now counts days.
- Remove `ALGOLIA_*` from the prod `.env`: those values match the key already built into the code, and a stale copy would override it after a key rotation.
- Create the mirror directory before setting `TRACKAROO_BACKUP_MIRROR_DIR`. Trackaroo never creates it.

**Still open in #15:** the unused Algolia settings, the requirements split and pinning, the run lock, and scoping of alert deletes. The logs mount and log rotation land in the phase 6 PR.

## Gate at phase close
pytest 1017, vitest 475, Playwright 71, svelte-check 0 errors, 0 warnings. The gate at the top of the stack is in the phase 6 PR.

Not deployed yet. That happens in phase 6, and issues stay open until prod has been verified.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
