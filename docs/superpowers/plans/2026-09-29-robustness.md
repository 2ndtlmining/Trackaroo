# Robustness Implementation Plan (Phase 3 of the 28-Sep roadmap)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A retailer that fails, comes back empty, is locked out, times out or never reports is retried the same morning and pages someone the same day. None of those failures can skip the digest gate, the alerts or the backup. CI proves every commit builds and boots without scraping.

**Architecture:**
1. `run_daily.py` becomes a `run(args) -> int` function. Each best-effort step goes through one `best_effort()` wrapper and each health check through `guarded_check()`. The backup runs in a `finally`, and `main()` catches a crash and turns it into an alert and exit 1.
2. Scrapers report through **exit codes**: 0 ok, 2 degraded, 3 skipped (cooldown), 4 auth (a rejected key). They also write a small **run report** JSON (per-category matched, pages and cards) to a path `run_daily` passes in `TRACKAROO_RUN_REPORT`. Each category's report is flushed as soon as that category is done, so the counts survive a timeout kill.
3. Three small bookkeeping tables, created through `migrate.py` and `db/schema.sql`:
   - `active_retailers` is the one source of truth the web app reads for "which retailers exist" (R1).
   - `scrape_runs` has one row per scraper run: status, time and matched count. It drives the hourly retry (#8) and the time shown on the health strip (R3).
   - `run_markers` holds once-per-day claims, so retries do not repeat the digest or an identical alert.
4. The entrypoints stop deciding anything. Every hour they call `python run_daily.py --scheduled`, which works out the window and which retailers are still pending.
5. New external side effects are opt-in env vars that are no-ops by default: `TRACKAROO_HEARTBEAT_URL` and `TRACKAROO_BACKUP_MIRROR_DIR`. Phase 6 switches them on.

**Tech Stack:** Python 3.12 + pytest (pipeline), SvelteKit 2 / Svelte 5 + vitest + Playwright (web), SQLite, POSIX sh (entrypoints), GitHub Actions, Docker.

**Spec:** Issues #7, #8, #9, #10, #11 (a), #12, #13, #14 and #15 (the adjacent parts only). Read them with `gh issue view N`. Also read the 28-Sep roadmap, `docs/superpowers/plans/2026-09-28-roadmap.md`: its "Phase 3 outline", R1–R4 under "Findings not in any issue", and "Follow-ups found while executing Phases 1–2".

## Global Constraints

- **Never delete `price_snapshots` rows.** Every schema change goes through `migrate.py` (idempotent, create-if-missing) **and** `db/schema.sql`, together, in the same commit.
- **Tests never make real network requests to retailers.** Mock `requests` or HTTP. From Task 8 the pytest suite blocks every non-loopback socket. **CI never scrapes:** the Docker job boots with `--network none` and `SKIP_PIPELINE=1`.
- **Every new external side effect is opt-in** via an env var and is a no-op when that var is unset: the heartbeat (`TRACKAROO_HEARTBEAT_URL`) and the backup mirror (`TRACKAROO_BACKUP_MIRROR_DIR`).
- **Windows dev machine:**
  - No unicode arrows in Python log output. Use `->`. New log strings in this plan use `-`, not `—`.
  - Shell scripts stay LF. `unit_testing/test_shell_scripts.py` enforces this.
- **The four-suite gate is green before every commit:**
  - from the repo root: `python -m pytest -q`
  - from `web/`: `npm run check`, `npm test`, `npm run test:e2e`
- **No redeploy in this plan.** The owner redeploys once, in Phase 6, with docker compose. Until then there is no docker-compose (CLAUDE.md), and Dockerfile and entrypoint changes are build-tested only. **Never run the image or the entrypoints against real data, and never start a live scrape.** The one exception is the fixture capture in Task 7, which needs the owner's OK.
- **Best-effort steps never break a run that has already collected good data** (CLAUDE.md, "Pipeline conventions"). Informational checks return WARNING, not ERROR.
- **The PCCG query budget stays at 2 queries per run.** `unit_testing/test_pccg_query_budget.py` must stay green.
- **Entry points call `config.setup_logging()`**, not `logging.basicConfig`.
- **Every commit message ends with the line** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A `--pccg` retry that the cooldown skips must not page "all scrapers failed".** The only outcome is `skipped`, so the run exits 0 and sends no alert. Pinned in Task 1 (`test_a_cooldown_skip_alone_is_not_a_failure`).
2. **Hourly retries must not repeat the Discord digest or an identical alert.** Two runs on the same day produce one digest and one alert. Pinned in Task 4 (`TestOncePerDay`).
3. **Deploy day: the DB already holds today's snapshots from the old build but has no `scrape_runs` rows.** That retailer is *not* pending, so the upgrade does not re-scrape it. Pinned in Task 4 (`test_pre_upgrade_day_with_snapshots_is_not_pending`).
4. **A scraper that saves per category must still never replace a fuller on-disk snapshot with a partial one.** The no-downgrade guard in `snapshot_io.save_snapshot` still applies, and the weaker result goes to a `.partial-*` sidecar. Pinned in Task 5 (`test_incremental_save_never_downgrades`).
5. **The web app must still render against a DB from before this phase**, where `active_retailers` and `scrape_runs` do not exist. Both the health strip and `/healthz` must work there. Pinned in Task 3 (`falls back to retailers with data when active_retailers is missing`) and Task 5 (`works without a scrape_runs table`).

---

## Design choices the owner may want to override

| # | Choice | Why |
|---|---|---|
| D1 | **Where the web learns the active-retailer list:** a DB table, `active_retailers`, rewritten from `config.ACTIVE_RETAILERS` by `seed.py` (every boot) and by `run_daily.py` (every run). | The web already reads only the DB. A JSON file would couple it to the `data/` layout, and a config export would need a build step. |
| D2 | **How scrapers report:** exit codes 0/2/3/4, plus a run-report JSON at a temp path `run_daily` passes in `TRACKAROO_RUN_REPORT`. | The exit code survives anything except a kill; the report survives the kill because it is flushed per category. |
| D3 | **`RETRY_UNTIL_HOUR` defaults to 9, not the issue's 12.** | #8 asks for both "alert by 10:00" and "threshold 0 past the retry cutoff". Both can only hold if the cutoff is before `STALENESS_CHECK_HOUR` (10). |
| D4 | **The staleness monitor's default threshold goes from 1 to 0 days.** A retailer missing today is an ERROR at 10:00 unless an active PCCG cooldown explains it. So is a retailer that has never reported (R1). | #8's off-by-one: at 10:00 on a missed day, yesterday's data read as fresh. |
| D5 | **The digest is blocked by any scraper problem, not only by health ERRORs.** It is sent at most once a day, via `run_markers`. | #7: the digest must not fire "as if the run were clean". Retries would otherwise post it twice. |
| D6 | **Partial results are kept by saving per category**, not by per-page streaming and not by a longer timeout. `SCRAPER_TIMEOUT_SECONDS` stays at 300. | A timeout now loses at most the unfinished category, and the hourly retry fetches it. |
| D7 | **`TRACKAROO_BACKUP_KEEP` now means days.** The newest backup of each of the last N days is kept, plus the 3 newest overall. The docs already called it days. There is no weekly/monthly GFS tier (YAGNI). | Retries make several backups a day, and count-based pruning then covered only a few days (#10). |
| D8 | **`quick_check` runs on the new backup, not also on the live DB.** | The online-backup API copies pages 1:1, so a corrupt live DB yields a failing backup. That saves a second full scan every morning. |
| D9 | **`/healthz` `ok` means "the web process can open and query the DB".** Freshness is reported, but it never makes the check unhealthy. | Staleness is the heartbeat's and the staleness monitor's job. A stale-but-running container must not be restarted by autoheal. |
| D10 | **CI runs vitest and Playwright on the synthetic snapshots `e2e/seed.mjs` already falls back to.** A new `write-synthetic-data.mjs` writes them to `data/`. | `data/` is gitignored, and committing 3.9 MB of real scrapes was rejected as the alternative. |
| D11 | **Scraper fixtures are captured live, once, by hand** with `unit_testing/fixtures/capture_fixtures.py`: 3 requests, 1 of which is an Algolia query. They are then committed. | The owner asked for *real* HTML/JSON. No test ever runs the capture. The owner must OK the capture. |
| D12 | **#15 is limited to the Umart thresholds (Task 2) and the `PRICE_MOVE_PCT` doc fix (Task 11).** | The dead knobs, the logs mount, pinned deps, the run lock and alert-delete scoping stay in #15 for later. |

## Verified starting points (re-checked 29-Sep on `feat/2026-09-29-robustness`)

| Audit said | Actual location now |
|---|---|
| `run_daily.py:82` checks only returncode | `run_daily.py:60-97` (`run_scraper`) |
| all-fail `sys.exit(1)` at :233 | `run_daily.py:233-235` |
| `run_notify` :346, `send_alert` :362 unwrapped | `run_daily.py:345-346` and `:350-362`; the backup at `:380-383` is also unwrapped |
| PCCG breaker only logs (~731) | `scraper/pccg.py:689-694` (main) and `:590-600` (`scrape_category`) |
| `json_match_count` WARNING (~121) | `health_checks.py:117-131` |
| `today_coverage` WARNING (~331) | `health_checks.py:318-337` |
| `config.py` ~127-130 has no umart | confirmed, `config.py:127-130` |
| entrypoint runs only at `RUN_AT_HOUR` (~185-199) | `deploy/entrypoint-single.sh:182-202`, and `deploy/entrypoint.sh:79-89` too |
| `todays_run_done` any snapshot (~94-104) | `deploy/entrypoint-single.sh:84-106`, `deploy/entrypoint.sh:40-62` |
| `check_staleness.py:47` threshold 1, `>` at :117 | `check_staleness.py:45` and `:119` (per retailer `:159`) |
| `json.load` uncaught (~348) | `ingest.py:452-453` |
| pccg key (52-53) / `.env.example:8-9` | `scraper/pccg.py:54-55`; `.env.example:8-9` confirmed |
| no `.github/` | confirmed |
| existing fixtures | only `unit_testing/fixtures/titles.csv`. `test_umart.py` and `test_scraper.py` carry small inline HTML samples. |

Test counts at the start of this phase (STATUS.md, 29-Sep): pytest **863**, vitest **462**, Playwright **71**, svelte-check **0 errors**.

---

## File Structure

| File | Responsibility |
|---|---|
| `run_daily.py` | The run: `ScrapeOutcome`, `run_scraper`, `run(args) -> int`, `best_effort`, `guarded_check`, `run_db_checks`, retry and window logic, once-per-day claims, heartbeat call |
| `pipeline_state.py` (new) | Read/write helpers for the bookkeeping tables: `ensure_ops_tables`, `sync_active_retailers`, `record_scrape_run`, `retailers_pending`, `claim_marker` |
| `migrate.py`, `db/schema.sql` | DDL for `active_retailers`, `scrape_runs`, `run_markers` |
| `scraper/run_report.py` (new) | Exit codes, `RunReport` (per-category counters, flushed per category), `read_run_report`, `exit_code_for` |
| `scraper/snapshot_io.py` | Adds `save_category_snapshot` (one category, through the no-downgrade guard) |
| `scraper/scorptec.py`, `scraper/umart.py`, `scraper/pccg.py` | Exit codes, per-category save, telemetry counters, the PCCG auth error |
| `health_checks.py` | ERROR for zero matched and for a missing retailer, `cooldown_explains`, `check_run_report`, `check_match_count_drop`, `check_backups` |
| `check_staleness.py` | Threshold 0; a missing retailer is an ERROR unless a cooldown explains it |
| `heartbeat.py` (new) | `ping()`: GET `TRACKAROO_HEARTBEAT_URL`; no-op when it is unset |
| `backup_db.py` | `quick_check`, age-based `prune_backups`, `mirror_backup`, typed errors |
| `restore_drill.py` (new) | Restores the newest backup to a temp file, then runs `quick_check`, row counts and per-day comparison with live |
| `config.py` | `RUN_AT_HOUR`, `RETRY_UNTIL_HOUR`, the Umart thresholds, `MATCH_DROP_*`, `BACKUP_MIRROR_DIR`, `BACKUP_MAX_AGE_HOURS` |
| `seed.py` | Syncs `active_retailers` on every boot |
| `deploy/entrypoint-single.sh`, `deploy/entrypoint.sh`, `deploy/bootstrap-data.sh` | Hourly `--scheduled`, boot `--pending-only`, `SKIP_PIPELINE`, ingest made non-fatal |
| `Dockerfile` | `ARG GIT_SHA` -> `TRACKAROO_VERSION`, `HEALTHCHECK` on `/healthz` |
| `.github/workflows/ci.yml` (new) | backend, web (plus the node smoke test) and docker jobs |
| `web/src/lib/server/repos.ts` | `getRetailerFreshness`: every active retailer, plus the last run's time, status and matched count |
| `web/src/lib/health.ts`, `web/src/lib/components/HealthStrip.svelte` | "missing", "today 04:12", an "incomplete" state, a matched-count detail |
| `web/src/routes/healthz/+server.ts` (new) | JSON `{ok, version, retailers[]}` |
| `web/e2e/seed.mjs`, `web/e2e/write-synthetic-data.mjs` (new), `web/test/helpers/seed.ts` | Synthetic data for CI; e2e seeds an active retailer with no rows |
| `unit_testing/conftest.py` | `isolated_pipeline` fixture; the no-network guard |
| `unit_testing/fixtures/*` | Real trimmed HTML/JSON per retailer plus the capture script |
| `DEPLOYMENT.md`, `.env.example`, `STATUS.md` | Runbooks and the env-var table |

---

### Task 1: Best-effort steps, an alert on the all-fail path, and bad-JSON skip (#12, R4)

**Files:**
- Modify: `run_daily.py` (imports; `run_scraper` `:60-97`; `ingest_today` `:100-128`; `main` `:209-383` becomes `main` plus `run`)
- Modify: `ingest.py:452-453` (`ingest_file`)
- Modify: `deploy/bootstrap-data.sh:96` (the hydrate ingest must not kill the boot)
- Modify: `unit_testing/conftest.py` (add the `isolated_pipeline` fixture)
- Modify: `unit_testing/test_cli.py:111-171` (fakes return `ScrapeOutcome`, `run_db_checks` patched)
- Create: `unit_testing/test_run_daily_resilience.py`

**Interfaces:**
- Produces, in `run_daily`:
  - `@dataclass ScrapeOutcome(retailer: str, status: str, exit_code: Optional[int] = None, started_at: str = "", finished_at: str = "", matched: Optional[int] = None, detail: str = "", report: Optional[Dict[str, Any]] = None)`, with the properties `.ok -> bool` and `.needs_alert -> bool`.
  - `SCRAPE_STATUSES = ("ok", "degraded", "skipped", "auth", "failed", "timeout")`
  - `status_for_exit(code: int) -> str`
  - `outcome_alert_line(o: ScrapeOutcome) -> str`
  - `run_scraper(name: str, module: str, label: str) -> ScrapeOutcome`
  - `best_effort(label: str, fn, *args, **kwargs) -> Any` (returns None when `fn` raised)
  - `guarded_check(name: str, check: Callable[[], List[CheckResult]]) -> List[CheckResult]`
  - `_db_checks() -> List[Tuple[str, Callable[[], List[CheckResult]]]]`
  - `run_db_checks() -> List[CheckResult]`
  - `alerts_enabled(args) -> bool`
  - `send_pipeline_alert(lines: List[str]) -> None`
  - `run(args: argparse.Namespace) -> int`
  - `RUN_EXIT_OK = 0`, `RUN_EXIT_ALL_FAILED = 1`, `RUN_EXIT_DEGRADED = 2`
  - `ingest_today(conn, dry_run=False) -> Dict[str, Any]`, whose result now includes `"bad_files": List[str]`
- Produces, in `ingest`: `ingest_file()` never raises on an unreadable file. It returns stats with `"unreadable": 1` and `"errors": 1`.
- Produces, in `conftest`: the fixture `isolated_pipeline`. It is a `SimpleNamespace` with `.alerts: List[List[str]]`, `.digests: int`, `.price_alert_runs: int`, `.backups: int`, `.delisted_runs: int`, `.db_path: Path` and `.data_dir: Path`.

- [ ] **Step 1: Add the `isolated_pipeline` fixture to `unit_testing/conftest.py`**

Add `import types` to the imports, then append:

```python
# ── run_daily end-to-end harness ─────────────────────────────────────

@pytest.fixture
def isolated_pipeline(monkeypatch, tmp_path):
    """Run ``run_daily.run()`` end to end with every side effect faked.

    The DB is a real file DB (so several connections see the same rows), the
    data dir is a temp dir, and the digest, alerts, price alerts, delisted
    check, JSON mirror and backup are recorded instead of performed. Each test
    still chooses what the scrapers return by patching ``run_daily.run_scraper``.
    Health checks are off by default (``run_db_checks`` / ``check_json_files``
    return nothing); a test that wants one re-patches it.
    """
    import run_daily

    calls = types.SimpleNamespace(
        alerts=[], digests=0, price_alert_runs=0, backups=0, delisted_runs=0,
        db_path=tmp_path / "pipeline.db", data_dir=tmp_path / "data",
    )
    calls.data_dir.mkdir()
    conn = sqlite3.connect(str(calls.db_path))
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()

    def fake_init_db(path):
        c = sqlite3.connect(str(calls.db_path))
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def fake_digest(*a, **k):
        calls.digests += 1

    def fake_price_alerts(*a, **k):
        calls.price_alert_runs += 1

    def fake_backup(**k):
        calls.backups += 1

    def fake_delisted(*a, **k):
        calls.delisted_runs += 1

    monkeypatch.setattr(run_daily, "init_db", fake_init_db)
    monkeypatch.setattr(run_daily, "DB_PATH", calls.db_path)
    monkeypatch.setattr(run_daily, "DATA_DIR", calls.data_dir)
    monkeypatch.setattr(run_daily, "SCRAPER_GAP_SECONDS", 0)
    monkeypatch.setattr(run_daily, "check_json_files", lambda *a, **k: [])
    monkeypatch.setattr(run_daily, "run_db_checks", lambda *a, **k: [])
    monkeypatch.setattr("export_snapshots.run", lambda **k: {"recovered": 0, "written": 0})
    monkeypatch.setattr("check_delisted.run", fake_delisted)
    monkeypatch.setattr("check_stale_listings.run", lambda *a, **k: None)
    monkeypatch.setattr("notify_discord.run", fake_digest)
    monkeypatch.setattr(
        "notify_discord.send_alert",
        lambda lines, dry_run=False: calls.alerts.append(list(lines)) or 1,
    )
    monkeypatch.setattr("check_alerts.run", fake_price_alerts)
    monkeypatch.setattr("backup_db.backup_database", fake_backup)
    return calls
```

- [ ] **Step 2: Write the failing tests**

Create `unit_testing/test_run_daily_resilience.py`:

```python
"""run_daily must finish its best-effort steps whatever one of them does (#12, R4)."""
import json
import sqlite3

import pytest

import run_daily
from health_checks import CheckResult
from ingest import ingest_file


def _outcome(status):
    code = {"ok": 0, "skipped": 3}.get(status, 1)
    return lambda name, module, label: run_daily.ScrapeOutcome(label, status, code)


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


def _today_file(data_dir, retailer, category, body):
    path = data_dir / f"{category}_{retailer}_{run_daily.today_filename()}.json"
    path.write_text(body, encoding="utf-8")
    return path


GOOD = {
    "retailer": "scorptec", "category": "cpu", "matched": 1,
    "products": [{
        "watchlist_model": "Ryzen 7 9800X3D", "watchlist_category": "cpu",
        "watchlist_brand": "AMD", "watchlist_gen_tier": "current",
        "retailer": "scorptec", "price_aud": 599.0, "stock_status": "in_stock",
        "url": "https://www.scorptec.com.au/product/cpu/amd-socket-am5/111111",
    }],
}


def _boom(*a, **k):
    raise sqlite3.OperationalError("no such table: products")


class TestBestEffortSteps:
    def test_digest_crash_still_runs_price_alerts_and_backup(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr("notify_discord.run", _boom)
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("ok"))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_OK
        assert isolated_pipeline.price_alert_runs == 1
        assert isolated_pipeline.backups == 1

    def test_alert_delivery_crash_still_backs_up(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr("notify_discord.send_alert", _boom)
        monkeypatch.setattr(
            run_daily, "run_scraper",
            lambda n, m, label: run_daily.ScrapeOutcome(label, "failed" if label == "umart" else "ok", 1),
        )

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert isolated_pipeline.backups == 1

    def test_backup_crash_does_not_raise(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr("backup_db.backup_database", _boom)
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("ok"))

        assert run_daily.run(_args()) == run_daily.RUN_EXIT_OK

    def test_a_crashing_health_check_is_reported_as_an_error(self, monkeypatch):
        def crashes():
            raise ValueError("bad date")

        monkeypatch.setattr(run_daily, "_db_checks", lambda: [
            ("check_fine", lambda: [CheckResult("fine", CheckResult.OK, "ok")]),
            ("check_price_anomalies", crashes),
        ])

        results = run_daily.run_db_checks()

        assert [(r.check_name, r.status) for r in results] == [
            ("fine", CheckResult.OK),
            ("check_price_anomalies_crashed", CheckResult.ERROR),
        ]
        assert "ValueError: bad date" in results[1].message


class TestAllScrapersFailed:
    def test_sends_an_alert_before_exiting_non_zero(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("failed"))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_ALL_FAILED
        assert len(isolated_pipeline.alerts) == 1
        text = "\n".join(isolated_pipeline.alerts[0])
        assert "All scrapers failed" in text
        for label in ("Scorptec", "PCCG", "Umart"):
            assert label in text
        assert isolated_pipeline.backups == 0  # nothing new was written

    def test_main_exits_1(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("failed"))
        with pytest.raises(SystemExit) as exc:
            run_daily.main([])
        assert exc.value.code == 1

    def test_a_cooldown_skip_alone_is_not_a_failure(self, isolated_pipeline, monkeypatch):
        """Review Focus 1: a --pccg retry skipped by the cooldown must not page."""
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("skipped"))

        assert run_daily.run(_args("--pccg")) == run_daily.RUN_EXIT_OK
        assert isolated_pipeline.alerts == []

    def test_a_crash_inside_the_run_still_alerts(self, isolated_pipeline, monkeypatch):
        def crash(args):
            raise RuntimeError("disk full")

        monkeypatch.setattr(run_daily, "run", crash)
        with pytest.raises(SystemExit) as exc:
            run_daily.main([])
        assert exc.value.code == 1
        assert "crashed" in "\n".join(isolated_pipeline.alerts[0])


class TestBadJsonFile:
    def test_ingest_file_reports_instead_of_raising(self, db, tmp_path):
        path = tmp_path / f"gpu_pccg_{run_daily.today_filename()}.json"
        path.write_text("{not json", encoding="utf-8")

        stats = ingest_file(db, path)

        assert stats["unreadable"] == 1
        assert stats["errors"] == 1

    def test_a_non_object_file_is_unreadable_too(self, db, tmp_path):
        path = tmp_path / f"gpu_pccg_{run_daily.today_filename()}.json"
        path.write_text("[]", encoding="utf-8")

        assert ingest_file(db, path)["unreadable"] == 1

    def test_one_corrupt_file_does_not_stop_the_others(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
        bad = _today_file(tmp_path, "pccg", "cpu", "{not json")  # sorts first
        _today_file(tmp_path, "scorptec", "cpu", json.dumps(GOOD))

        stats = run_daily.ingest_today(db)

        assert stats["inserted"] == 1
        assert stats["bad_files"] == [bad.name]

    def test_the_run_reports_it_as_an_error_and_alerts(self, isolated_pipeline, monkeypatch):
        _today_file(isolated_pipeline.data_dir, "pccg", "cpu", "{not json")
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("ok"))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert any("unreadable" in line for line in isolated_pipeline.alerts[0])
        assert isolated_pipeline.digests == 0
        assert isolated_pipeline.backups == 1
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest unit_testing/test_run_daily_resilience.py -q`

Expected: FAIL with `AttributeError: module 'run_daily' has no attribute 'ScrapeOutcome'` (and similar for `run`, `RUN_EXIT_OK`).

- [ ] **Step 4: Make `ingest_file` survive an unreadable file**

In `ingest.py`, replace

```python
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)
```

with

```python
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        # One corrupt file used to abort the whole ingest -- and with it the
        # remaining files, the JSON mirror, the health checks and the backup
        # (#12). json.JSONDecodeError and UnicodeDecodeError are ValueErrors.
        LOGGER.error("Skipping unreadable snapshot %s: %s", file_path.name, e)
        stats["errors"] += 1
        stats["unreadable"] = 1
        return stats
    if not isinstance(data, dict):
        LOGGER.error("Skipping %s: expected a JSON object, got %s",
                     file_path.name, type(data).__name__)
        stats["errors"] += 1
        stats["unreadable"] = 1
        return stats
```

`ingest.main()` already accumulates `errors`. It exits 1 at the end, but only after processing every file.

- [ ] **Step 5: Rework `run_daily.py`**

Replace the imports block (`:19-50`) with:

```python
import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import (
    ACTIVE_RETAILERS,
    BACKUP_KEEP,
    DATA_DIR,
    DB_DATE_FORMAT,
    DB_PATH,
    FILE_DATE_FORMAT,
    SCRAPER_GAP_SECONDS,
    SCRAPER_TIMEOUT_SECONDS,
    setup_logging,
)
from health_checks import (
    CheckResult,
    check_db_freshness,
    check_json_db_parity,
    check_json_files,
    check_match_count_anomalies,
    check_missing_days,
    check_scraper_cooldown,
    check_price_anomalies,
    check_spec_coverage,
    check_today_coverage,
)
from ingest import init_db
```

After `today_filename()`, replace `run_scraper` (`:60-97`) with:

```python
# Process exit codes for run_daily itself. The entrypoints log any non-zero as
# "finished with errors" and carry on; DEPLOYMENT.md documents these.
RUN_EXIT_OK = 0
RUN_EXIT_ALL_FAILED = 1   # nothing was scraped, or the run crashed
RUN_EXIT_DEGRADED = 2     # a scraper or health check failed; good data was kept

# What one scraper run can end as. scrape_runs.status (Task 4) uses the same set.
SCRAPE_STATUSES = ("ok", "degraded", "skipped", "auth", "failed", "timeout")

_OUTCOME_TEXT = {
    "degraded": "returned an incomplete result",
    "skipped": "was skipped (cooldown active - expected)",
    "auth": "was refused by the retailer (credentials rejected) - needs a human",
    "failed": "failed",
    "timeout": f"timed out after {SCRAPER_TIMEOUT_SECONDS}s",
}


@dataclass
class ScrapeOutcome:
    """What one scraper subprocess did (#7, #8, R3)."""
    retailer: str
    status: str                        # one of SCRAPE_STATUSES
    exit_code: Optional[int] = None
    started_at: str = ""               # local ISO8601, seconds
    finished_at: str = ""
    matched: Optional[int] = None      # products matched (from the run report)
    detail: str = ""
    report: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def needs_alert(self) -> bool:
        """Everything except success and an expected cooldown skip pages someone."""
        return self.status not in ("ok", "skipped")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def status_for_exit(code: int) -> str:
    """Map a scraper's exit code to a ScrapeOutcome status."""
    return "ok" if code == 0 else "failed"


def outcome_alert_line(o: ScrapeOutcome) -> str:
    """One Discord bullet describing a scraper problem."""
    label = SCRAPERS[o.retailer][0] if o.retailer in SCRAPERS else o.retailer.title()
    text = _OUTCOME_TEXT.get(o.status, o.status)
    if o.status == "failed" and o.exit_code is not None:
        text += f" (exit code {o.exit_code})"
    if o.detail:
        text += f": {o.detail}"
    return f"- Scraper **{label}** {text}"


def run_scraper(name: str, module: str, label: str) -> ScrapeOutcome:
    """Run a scraper module as a subprocess and classify what happened.

    Args:
        name: Display name (e.g. 'Scorptec')
        module: Python module path (e.g. 'scraper.scorptec')
        label: Retailer slug (e.g. 'scorptec')
    """
    LOGGER.info("\n%s\nScraping %s...\n%s", "=" * 60, name, "=" * 60)
    started = _now()
    start = time.time()
    status, exit_code = "failed", None
    try:
        result = subprocess.run(
            [sys.executable, "-m", module],
            capture_output=False,
            text=True,
            timeout=SCRAPER_TIMEOUT_SECONDS,
        )
        exit_code = result.returncode
        status = status_for_exit(exit_code)
    except subprocess.TimeoutExpired:
        status = "timeout"
    except Exception as e:  # noqa: BLE001 - CLI wrapper reports any failure
        LOGGER.error("\n%s error: %s", name, e)

    outcome = ScrapeOutcome(label, status, exit_code, started_at=started, finished_at=_now())
    elapsed = time.time() - start
    if outcome.ok:
        LOGGER.info("\n%s completed in %.1fs", name, elapsed)
    else:
        LOGGER.error("\n%s %s (exit code %s) after %.1fs", name, status, exit_code, elapsed)
    return outcome
```

(`SCRAPERS` is defined further down the module. `outcome_alert_line` reads it at call time, so the order is fine.)

Replace `ingest_today` (`:100-128`) with:

```python
def ingest_today(conn: Any, dry_run: bool = False) -> Dict[str, Any]:
    """Ingest all JSON files for today's date.

    A file that cannot be read is skipped and named in ``bad_files`` rather
    than aborting the rest (#12).

    Returns:
        Stats dict with inserted/skipped/errors counts and ``bad_files``, or
        {} when there are no files for today.
    """
    from ingest import ingest_file

    today = today_filename()
    files = sorted(DATA_DIR.glob(f"*_{today}.json"))

    if not files:
        LOGGER.info("\nNo JSON files found for today (%s)", today)
        return {}

    total_stats: Dict[str, Any] = {"inserted": 0, "skipped": 0, "errors": 0, "bad_files": []}

    for f in files:
        LOGGER.info("\n  Ingesting: %s", f.name)
        try:
            stats = ingest_file(conn, f, dry_run=dry_run)
        except Exception:  # noqa: BLE001 - one file must never stop the rest
            LOGGER.exception("Ingest of %s crashed - skipping it", f.name)
            total_stats["errors"] += 1
            total_stats["bad_files"].append(f.name)
            continue
        if stats.get("unreadable"):
            total_stats["bad_files"].append(f.name)
        total_stats["inserted"] += stats["inserted"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["errors"] += stats["errors"]

    return total_stats
```

After `notify_enabled`, add:

```python
def alerts_enabled(args: argparse.Namespace) -> bool:
    """True when pipeline-issue alerts may be sent.

    Every real run alerts, including --no-health and --scrape-only ones; only a
    dry run or an explicit --no-notify stays silent.
    """
    return not (args.dry_run or args.no_notify)


def best_effort(label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run one best-effort pipeline step (#12, R4).

    CLAUDE.md: steps after ingest must never break a run that already
    collected good data. Any exception is logged with its traceback and
    swallowed.

    Returns:
        ``fn``'s return value, or None when it raised.
    """
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 - best-effort by contract
        LOGGER.exception("%s failed (best-effort; the run continues)", label)
        return None


def guarded_check(name: str, check: Callable[[], List[CheckResult]]) -> List[CheckResult]:
    """Run one health check; a crash becomes an ERROR result, never an exception (R4)."""
    try:
        return list(check())
    except Exception as e:  # noqa: BLE001 - a broken check must still be reported
        LOGGER.exception("Health check %s crashed", name)
        return [CheckResult(f"{name}_crashed", CheckResult.ERROR,
                            f"{name} raised {type(e).__name__}: {e}")]


def _db_checks() -> List[Tuple[str, Callable[[], List[CheckResult]]]]:
    """The post-ingest DB checks, in report order.

    Lambdas look the check functions up at call time, so tests can patch them
    on this module.
    """
    return [
        ("check_db_freshness", lambda: check_db_freshness(DB_PATH)),
        ("check_today_coverage", lambda: check_today_coverage(DB_PATH)),
        ("check_match_count_anomalies", lambda: check_match_count_anomalies(DB_PATH)),
        ("check_price_anomalies", lambda: check_price_anomalies(DB_PATH)),
        ("check_spec_coverage", lambda: check_spec_coverage(DB_PATH)),
        ("check_json_db_parity", lambda: check_json_db_parity(db_path=DB_PATH)),
        ("check_missing_days", lambda: check_missing_days(DB_PATH)),
        ("check_scraper_cooldown", lambda: check_scraper_cooldown()),
    ]


def run_db_checks() -> List[CheckResult]:
    """Every DB health check; one crashing check no longer skips the rest (R4)."""
    results: List[CheckResult] = []
    for name, check in _db_checks():
        results.extend(guarded_check(name, check))
    return results


def send_pipeline_alert(lines: List[str]) -> None:
    """Post a pipeline-issue alert to DISCORD_WEBHOOK_ALERT; never raises."""
    from notify_discord import send_alert
    best_effort("Pipeline alert", send_alert, lines)
```

Replace `main` (`:209-383`) with `main` plus `run`:

```python
def main(argv: Optional[List[str]] = None) -> None:
    setup_logging()
    args = build_parser().parse_args(argv)
    try:
        code = run(args)
    except Exception:  # noqa: BLE001 - last line of defence: a crash must still page
        LOGGER.exception("Daily run crashed")
        if alerts_enabled(args):
            send_pipeline_alert(["- **Daily run crashed** - see the log for the traceback."])
        code = RUN_EXIT_ALL_FAILED
    if code:
        sys.exit(code)


def run(args: argparse.Namespace) -> int:
    """One pipeline run. Returns the process exit code (RUN_EXIT_*)."""
    to_run = selected_retailers(args)

    LOGGER.info("Trackaroo daily run - %s", today_filename())
    LOGGER.info("Scraping: %s", "  |  ".join(SCRAPERS[r][0] for r in to_run))

    # ── Scrape ──────────────────────────────────────────────
    results: Dict[str, ScrapeOutcome] = {}
    for i, retailer in enumerate(to_run):
        if i:
            time.sleep(SCRAPER_GAP_SECONDS)  # Polite delay between scrapers
        label, module = SCRAPERS[retailer]
        results[retailer] = run_scraper(label, module, retailer)

    LOGGER.info("\n%s\nScrape summary:\n%s", "=" * 60, "=" * 60)
    for name, outcome in results.items():
        LOGGER.info("  %s %s", outcome.status.upper(), name)

    scraper_lines = [outcome_alert_line(o) for o in results.values() if o.needs_alert]

    if not any(o.ok for o in results.values()):
        if not scraper_lines:
            # Every selected scraper was deliberately skipped (a --pccg retry
            # during its cooldown): expected, and nothing new to ingest.
            LOGGER.info("\nEvery selected scraper was skipped - nothing to ingest.")
            return RUN_EXIT_OK
        # Nothing new to ingest or back up -- but this is the run that most
        # needs to page someone, and it used to exit before any alert (#12).
        LOGGER.error("\nAll scrapers failed. Aborting.")
        if alerts_enabled(args):
            send_pipeline_alert(["- **All scrapers failed** - no new data this run."] + scraper_lines)
        return RUN_EXIT_ALL_FAILED

    # ── Health check: validate JSON before ingestion ───────
    json_results: List[CheckResult] = []
    if not args.no_health:
        json_results = guarded_check("check_json_files", lambda: check_json_files(today_filename()))
        _report_results(json_results, "JSON validation")

    # ── Ingest ──────────────────────────────────────────────
    if args.scrape_only:
        LOGGER.info("\nScrape-only mode - skipping ingestion.")
        LOGGER.info("JSON files saved to data/")
        return RUN_EXIT_DEGRADED if scraper_lines else RUN_EXIT_OK

    ingest_results: List[CheckResult] = []
    db_results: List[CheckResult] = []
    failed: List[CheckResult] = []
    try:
        conn = init_db(DB_PATH)
        try:
            stats = ingest_today(conn, dry_run=args.dry_run)

            if stats:
                mode = "(DRY RUN)" if args.dry_run else ""
                LOGGER.info("\n%s\nIngestion summary %s:\n%s", "=" * 60, mode, "=" * 60)
                LOGGER.info("  Inserted: %d", stats["inserted"])
                LOGGER.info("  Skipped:  %d", stats["skipped"])
                LOGGER.info("  Errors:   %d", stats["errors"])
                LOGGER.info("%s", "=" * 60)
                if stats.get("bad_files"):
                    ingest_results.append(CheckResult(
                        "ingest_unreadable_json", CheckResult.ERROR,
                        "Skipped unreadable snapshot file(s): " + ", ".join(stats["bad_files"]),
                    ))
            else:
                LOGGER.info("\nNo new data to ingest.")

            if not args.dry_run:
                conn.commit()
        finally:
            conn.close()
        _report_results(ingest_results, "Ingest")

        # ── Mirror the DB back out to JSON ──────────────────────────────
        # data/*.json is the backup the DB is rebuilt from, so it must hold
        # every snapshot the DB does. Best-effort: never breaks the run.
        if not args.dry_run:
            try:
                from export_snapshots import run as run_export
                totals = run_export(dates=[date.today().strftime(DB_DATE_FORMAT)],
                                    repair_only=True)
                if totals["recovered"]:
                    LOGGER.warning(
                        "JSON backup was short by %d snapshot(s) - repaired %d file(s).",
                        totals["recovered"], totals["written"],
                    )
            except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                LOGGER.error("JSON mirror failed: %s", e)

        # ── Health check: validate DB state after ingestion ───
        if not args.no_health:
            db_results = run_db_checks()
            _report_results(db_results, "DB validation")
            ok_count = sum(1 for r in db_results if r.status == CheckResult.OK)
            if not any(r.status != CheckResult.OK for r in db_results):
                LOGGER.info("\nDB health: all %d checks passed", ok_count)

        # ── Delisted listing check (Scorptec) ───────────────────
        # Gated on a successful Scorptec scrape: a failed or empty one would
        # make every listing look delisted (#7d). Best-effort.
        scorptec = results.get("scorptec")
        if scorptec is not None and scorptec.ok and not args.dry_run:
            try:
                from check_delisted import run as run_delisted
                run_delisted()
            except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                LOGGER.error("Delisted check failed: %s", e)

        # ── Stale-listing check (all retailers) ─────────────────────────
        if not args.dry_run:
            try:
                from check_stale_listings import run as run_stale_listings
                run_stale_listings()
            except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                LOGGER.error("Stale-listing check failed: %s", e)

        failed = health_errors(json_results, ingest_results, db_results)

        # ── Discord digest + pipeline alerts ────────────────────────────
        if notify_enabled(args):
            if failed:
                LOGGER.warning("Skipping Discord digest - %d health check error(s).", len(failed))
            else:
                from notify_discord import run as run_notify
                best_effort("Discord digest", run_notify)

            alert_lines = list(scraper_lines)
            alert_lines += [f"- Health check error: {r}" for r in failed]
            # A missed run leaves no other trace, so surface calendar gaps too.
            alert_lines += [
                f"- {r.message}"
                for r in db_results
                if r.check_name == "missing_days" and r.status == CheckResult.WARNING
            ]
            if alert_lines:
                send_pipeline_alert(alert_lines)

            # ── Price-drop & restock alerts ───────────────────────────
            # Same clean-run gating: no "buy now" built on garbage data.
            if not failed:
                try:
                    from check_alerts import run as run_alerts
                    run_alerts()
                except Exception as e:  # noqa: BLE001 - best-effort, never breaks the run
                    LOGGER.error("Price alerts check failed: %s", e)
    finally:
        # ── Backup (automatic) ──────────────────────────────────────────
        # In a finally so that nothing above -- a crashed digest, a broken
        # health check -- can skip it (#12). Scrape-only and dry runs wrote
        # nothing and returned earlier / are excluded here.
        if not args.no_backup and not args.dry_run:
            from backup_db import backup_database
            LOGGER.info("\n%s\nBacking up database:\n%s", "=" * 60, "=" * 60)
            best_effort("Database backup", backup_database, keep=BACKUP_KEEP)

    return RUN_EXIT_DEGRADED if (scraper_lines or failed) else RUN_EXIT_OK
```

- [ ] **Step 6: Update the three `run_daily.main` tests in `unit_testing/test_cli.py`**

In `TestRunDailyMain`:
- `test_scorptec_dry_run`: change `fake_scraper` to `return run_daily.ScrapeOutcome(label, "ok", 0)`.
- `test_all_scrapers_failed`: change the patch to `lambda name, module, label: run_daily.ScrapeOutcome(label, "failed", 1)`, and after the `with` block add `assert exc.value.code == 1` (write `with pytest.raises(SystemExit) as exc:`).
- `test_alerts_failure_does_not_break_run`:
  - Change the `run_scraper` patch to `lambda name, module, label: run_daily.ScrapeOutcome(label, "ok", 0)`.
  - Replace the three lines that patch `check_db_freshness`, `check_today_coverage` and `check_match_count_anomalies` with `monkeypatch.setattr(run_daily, "run_db_checks", lambda: [])`. Without that, the unpatched checks run against the real `db/trackaroo.db` and can return ERRORs.

- [ ] **Step 7: Make the boot hydrate non-fatal**

`deploy/bootstrap-data.sh:96` runs under `set -e`, and `ingest.py` now exits 1 after *skipping* a bad file, so the hydrate ingest would crash-loop the container. Change

```sh
TRACKAROO_DATA_DIR=/app/seed-data python ingest.py
```

to

```sh
# ingest.py skips an unreadable file and exits 1 at the end (#12); the rest of
# the history is in, so a bad file must not crash-loop the container.
TRACKAROO_DATA_DIR=/app/seed-data python ingest.py || log "WARNING: ingest reported errors hydrating the seed data (see above) - continuing"
```

- [ ] **Step 8: Run the tests**

Run: `python -m pytest unit_testing/test_run_daily_resilience.py unit_testing/test_cli.py unit_testing/test_run_daily.py unit_testing/test_ingest.py unit_testing/test_shell_scripts.py -q`

Expected: all PASS.

- [ ] **Step 9: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add run_daily.py ingest.py deploy/bootstrap-data.sh unit_testing/conftest.py unit_testing/test_cli.py unit_testing/test_run_daily_resilience.py
git commit -m "fix(pipeline): best-effort steps can't skip alerts or backup; all-fail path alerts; bad JSON skipped (#12, R4)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: An empty scrape and a missing retailer alert; a cooldown only warns (#7 a, c, d; Umart thresholds from #15)

**Files:**
- Create: `scraper/run_report.py` (exit codes only in this task)
- Modify: `scraper/scorptec.py:448-496` (`main`), `scraper/umart.py:259-295` (`main`), `scraper/pccg.py:655-727` (`main`)
- Modify: `run_daily.py` (`status_for_exit`, digest gate)
- Modify: `health_checks.py:117-131` (`check_json_files`), `:284-345` (`check_today_coverage`); add `pccg_cooldown_remaining_hours`, `cooldown_explains`
- Modify: `config.py:127-130` (umart thresholds)
- Modify: `unit_testing/test_health_checks.py:806-818` (the missing-today test)
- Create: `unit_testing/test_scrape_outcomes.py`

**Interfaces:**
- Consumes: `ScrapeOutcome`, `run`, `isolated_pipeline` (Task 1).
- Produces, in `scraper.run_report`: `EXIT_OK = 0`, `EXIT_DEGRADED = 2`, `EXIT_SKIPPED = 3`, `EXIT_AUTH = 4`.
- Produces: `status_for_exit(0|2|3|4|other) -> "ok"|"degraded"|"skipped"|"auth"|"failed"`.
- Produces: each scraper's `main() -> int` (returns its exit code), with the module ending `raise SystemExit(main())`.
- Produces, in `health_checks`: `pccg_cooldown_remaining_hours(now: Optional[datetime] = None) -> float` and `cooldown_explains(retailer: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `unit_testing/test_scrape_outcomes.py`:

```python
"""A scrape that matched nothing is a failure that alerts; a cooldown skip is not (#7)."""
import pytest

import run_daily
from scraper import pccg, scorptec, umart
from scraper.run_report import EXIT_AUTH, EXIT_DEGRADED, EXIT_OK, EXIT_SKIPPED

WATCHLIST = [
    {"model": "Ryzen 7 9800X3D", "category": "cpu", "brand": "AMD", "gen_tier": "current",
     "vram_gb": None, "search_terms": ["ryzen 7 9800x3d"]},
    {"model": "GeForce RTX 5070", "category": "gpu", "brand": "NVIDIA", "gen_tier": "current",
     "vram_gb": 12, "search_terms": ["rtx 5070"]},
]


def _match(retailer, model, category):
    return {
        "watchlist_model": model, "watchlist_category": category,
        "watchlist_brand": "X", "watchlist_gen_tier": "current", "retailer": retailer,
        "scraped_name": model.lower(), "price_aud": 500.0, "stock_status": "in_stock",
        "url": f"https://example.com/{retailer}/{category}/1", "retailer_sku": "1",
    }


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


@pytest.mark.parametrize("code,status", [
    (EXIT_OK, "ok"), (EXIT_DEGRADED, "degraded"), (EXIT_SKIPPED, "skipped"),
    (EXIT_AUTH, "auth"), (1, "failed"), (-9, "failed"),
])
def test_status_for_exit(code, status):
    assert run_daily.status_for_exit(code) == status


class TestRunDailyReaction:
    def test_an_empty_scorptec_alerts_and_blocks_the_digest(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "degraded" if label == "scorptec" else "ok", 2 if label == "scorptec" else 0))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_DEGRADED
        assert any("Scorptec" in line and "incomplete" in line for line in isolated_pipeline.alerts[0])
        assert isolated_pipeline.digests == 0

    def test_an_empty_scorptec_skips_the_delisted_check(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "degraded" if label == "scorptec" else "ok", 2 if label == "scorptec" else 0))

        run_daily.run(_args())

        assert isolated_pipeline.delisted_runs == 0

    def test_a_cooldown_skip_warns_but_does_not_alert(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "skipped" if label == "pccg" else "ok", 3 if label == "pccg" else 0))

        code = run_daily.run(_args())

        assert code == run_daily.RUN_EXIT_OK
        assert isolated_pipeline.alerts == []
        assert isolated_pipeline.digests == 1


class TestScraperExitCodes:
    def test_scorptec_with_an_empty_gpu_category_is_degraded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scorptec, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(scorptec, "DATA_DIR", tmp_path)
        monkeypatch.setattr(scorptec, "scrape_scorptec", lambda wl, **k: (
            [_match("scorptec", "Ryzen 7 9800X3D", "cpu")], {0}, {}))

        assert scorptec.main() == EXIT_DEGRADED

    def test_scorptec_with_both_categories_is_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scorptec, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(scorptec, "DATA_DIR", tmp_path)
        monkeypatch.setattr(scorptec, "scrape_scorptec", lambda wl, **k: (
            [_match("scorptec", "Ryzen 7 9800X3D", "cpu"),
             _match("scorptec", "GeForce RTX 5070", "gpu")], {0, 1}, {}))

        assert scorptec.main() == EXIT_OK

    def test_umart_that_matched_nothing_is_degraded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(umart, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(umart, "DATA_DIR", tmp_path)
        monkeypatch.setattr(umart, "scrape_umart", lambda wl, **k: ([], set(), {}))

        assert umart.main() == EXIT_DEGRADED

    def test_pccg_in_cooldown_is_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pccg, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(pccg, "_cooldown_active", lambda: True)

        assert pccg.main() == EXIT_SKIPPED

    def test_pccg_breaker_trip_is_degraded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pccg, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(pccg, "DATA_DIR", tmp_path)
        monkeypatch.setattr(pccg, "_cooldown_active", lambda: False)
        monkeypatch.setattr(pccg, "CATEGORY_PASS_DELAY", 0)
        monkeypatch.setattr(pccg, "scrape_category", lambda category, wl, **k: ([], set(), True))

        assert pccg.main() == EXIT_DEGRADED
```

Append to `unit_testing/test_health_checks.py`, and add `from health_checks import cooldown_explains, pccg_cooldown_remaining_hours` to its imports:

```python
class TestZeroMatchIsAnError:
    def test_a_category_that_matched_nothing_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("health_checks.DATA_DIR", tmp_path)
        today = date.today().strftime("%d_%B_%Y")
        _make_json_file(tmp_path, "umart", "gpu", 0)

        results = check_json_files(today)

        [r] = [r for r in results if r.check_name == "json_match_count_umart_gpu"]
        assert r.status == CheckResult.ERROR
        assert "0 matched" in r.message


class TestCooldownExplains:
    def test_an_active_pccg_cooldown_explains_pccg_only(self, tmp_path, monkeypatch):
        cooldown = tmp_path / "pccg_cooldown.json"
        cooldown.write_text(json.dumps({"tripped_at": datetime.now().astimezone().isoformat(),
                                        "reason": "empty catalogue"}), encoding="utf-8")
        monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", cooldown)

        assert pccg_cooldown_remaining_hours() > 0
        assert cooldown_explains("pccg") is True
        assert cooldown_explains("umart") is False

    def test_no_cooldown_file_explains_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.PCCG_COOLDOWN_FILE", tmp_path / "absent.json")
        assert cooldown_explains("pccg") is False
```

In the same file, replace `TestCheckTodayCoverage.test_warns_for_retailer_missing_today` (`:806-818`) with these two tests (the setup is identical: yesterday's scorptec row only):

```python
    def _yesterday_only(self, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Test CPU', 1)")
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x.com/1', 'active')")
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, ?, 100, 'in_stock')", (yesterday,))
        conn.commit()
        conn.close()

    def test_a_retailer_missing_today_is_an_error(self, db_path, monkeypatch):
        """#7(c): silence from an active retailer pages someone, unless a cooldown explains it."""
        monkeypatch.setattr("health_checks.cooldown_explains", lambda retailer: False)
        self._yesterday_only(db_path)

        by_name = {r.check_name: r for r in check_today_coverage(db_path)}

        assert by_name["today_coverage_pccg"].status == CheckResult.ERROR
        assert "no snapshot for today" in by_name["today_coverage_pccg"].message
        assert by_name["today_coverage_umart"].status == CheckResult.ERROR

    def test_a_cooldown_turns_the_missing_retailer_into_a_warning(self, db_path, monkeypatch):
        monkeypatch.setattr("health_checks.cooldown_explains", lambda retailer: retailer == "pccg")
        self._yesterday_only(db_path)

        by_name = {r.check_name: r for r in check_today_coverage(db_path)}

        assert by_name["today_coverage_pccg"].status == CheckResult.WARNING
        assert "cooldown" in by_name["today_coverage_pccg"].message
        assert by_name["today_coverage_umart"].status == CheckResult.ERROR
```

Append to `unit_testing/test_config.py`:

```python
def test_umart_has_explicit_match_thresholds():
    """#7 / #15: Umart fell back to 10/5 against ~180 listings a day."""
    import config
    assert config.DEFAULT_MATCH_THRESHOLDS["umart"] == {"min_total": 90, "min_per_category": 10}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_scrape_outcomes.py unit_testing/test_health_checks.py unit_testing/test_config.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.run_report'`, then `ImportError` for `cooldown_explains`.

- [ ] **Step 3: Exit codes**

Create `scraper/run_report.py`:

```python
"""How a scraper tells run_daily what happened (#7, #11, R2, R3).

A scraper runs as a subprocess, so run_daily sees little more than its exit
code. Until 29-Sep-2026 every outcome -- a clean scrape, one that matched
nothing, a PCCG circuit-breaker trip, a cooldown skip -- exited 0, so a scrape
that matched nothing was logged "OK" and never alerted (#7). These codes keep
the four cases apart.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_DEGRADED = 2   # ran, but a category came back empty or the circuit breaker tripped
EXIT_SKIPPED = 3    # deliberately skipped (PCCG cooldown) -- expected, warns but never pages
EXIT_AUTH = 4       # the retailer rejected our credentials (PCCG Algolia 401/403) -- needs a human
```

In `run_daily.py`, add `from scraper.run_report import EXIT_AUTH, EXIT_DEGRADED, EXIT_OK, EXIT_SKIPPED` to the imports, and replace `status_for_exit` with:

```python
_STATUS_BY_EXIT = {EXIT_OK: "ok", EXIT_DEGRADED: "degraded",
                   EXIT_SKIPPED: "skipped", EXIT_AUTH: "auth"}


def status_for_exit(code: int) -> str:
    """Map a scraper's exit code to a ScrapeOutcome status (see scraper/run_report.py).

    1 (an uncaught exception) and a negative code (killed by a signal) are
    both plain failures.
    """
    return _STATUS_BY_EXIT.get(code, "failed")
```

- [ ] **Step 4: Scrapers return their exit code**

In `scraper/scorptec.py`:
- Add `from scraper.run_report import EXIT_DEGRADED, EXIT_OK`.
- Change `def main() -> None:` to `def main() -> int:`.
- After the final `save_snapshot(output_file, output_data)` loop, add:

```python
    # A category that came back empty is a failed scrape, not a quiet shop:
    # Scorptec always stocks both. It used to exit 0 and log "OK" (#7).
    if not cpu_results or not gpu_results:
        logger.error("Scorptec scrape incomplete: cpu=%d gpu=%d matched", len(cpu_results), len(gpu_results))
        return EXIT_DEGRADED
    return EXIT_OK
```

and change the module tail to

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

In `scraper/umart.py`:
- Add the same import.
- Make `main() -> int`.
- Before the `for category in ("cpu", "gpu"):` save loop, add `counts: Dict[str, int] = {}`.
- Inside the loop, after `products = [...]`, add `counts[category] = len(products)`.
- After the loop, add:

```python
    if not all(counts.values()):
        logger.error("Umart scrape incomplete: %s", counts)
        return EXIT_DEGRADED
    return EXIT_OK
```

Then change the tail to `raise SystemExit(main())`.

In `scraper/pccg.py`:
- Add `from scraper.run_report import EXIT_DEGRADED, EXIT_OK, EXIT_SKIPPED`.
- Make `main() -> int`.
- In the cooldown branch, replace the bare `return` with `return EXIT_SKIPPED`.
- After the final save loop, add:

```python
    per_category = {c: sum(1 for p in all_results if p["watchlist_category"] == c)
                    for c in ("cpu", "gpu")}
    # The breaker used to only log; the run still exited 0 and read "OK" (#7).
    if all_tripped or not all(per_category.values()):
        return EXIT_DEGRADED
    return EXIT_OK
```

Then change the tail to `raise SystemExit(main())`.

- [ ] **Step 5: Health checks**

In `health_checks.py`, replace the match-count block in `check_json_files` (`:117-131`) with:

```python
            # Check match count. Zero is a failed scrape, not a low day: every
            # retailer stocks both categories (#7). Below the threshold stays
            # a warning -- stock levels do move.
            matched = data.get("matched", 0)
            threshold = MATCH_THRESHOLDS.get(retailer, {}).get("min_per_category", DEFAULT_MIN_PER_CATEGORY)
            if matched == 0:
                results.append(CheckResult(
                    f"json_match_count_{retailer}_{category}",
                    CheckResult.ERROR,
                    f"0 matched products in {filename} - the scrape returned nothing for this category",
                ))
            elif matched < threshold:
                results.append(CheckResult(
                    f"json_match_count_{retailer}_{category}",
                    CheckResult.WARNING,
                    f"Low match count: {matched} (threshold: {threshold})",
                ))
            else:
                results.append(CheckResult(
                    f"json_match_count_{retailer}_{category}",
                    CheckResult.OK,
                    f"Match count OK: {matched}",
                ))
```

Add these above `check_today_coverage`:

```python
def pccg_cooldown_remaining_hours(now: Optional[datetime] = None) -> float:
    """Hours left on the PCCG circuit-breaker cooldown; 0.0 when none is active.

    Reads config.PCCG_COOLDOWN_FILE at call time so tests can point it at a
    temp file. An unreadable file counts as no cooldown -- the scraper treats
    it the same way (scraper/pccg.py _cooldown_active).
    """
    from config import PCCG_COOLDOWN_FILE, PCCG_COOLDOWN_HOURS

    try:
        payload = json.loads(PCCG_COOLDOWN_FILE.read_text(encoding="utf-8"))
        tripped_at = datetime.fromisoformat(payload["tripped_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0
    if tripped_at.tzinfo is None:
        tripped_at = tripped_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    remaining = (tripped_at + timedelta(hours=PCCG_COOLDOWN_HOURS) - now).total_seconds() / 3600
    return max(remaining, 0.0)


def cooldown_explains(retailer: str) -> bool:
    """True when an active scraper cooldown explains a retailer's silence today.

    Only PCCG has a cooldown. A retailer silent for any other reason is a
    failure that must page (#7c).
    """
    return retailer == "pccg" and pccg_cooldown_remaining_hours() > 0
```

In `check_today_coverage`, replace the `else:` branch that appends the WARNING (`:332-337`) with:

```python
            elif cooldown_explains(retailer):
                results.append(CheckResult(
                    f"today_coverage_{retailer}",
                    CheckResult.WARNING,
                    f"{retailer}: no snapshot for today ({today}) yet - scraper cooldown "
                    f"active, expected",
                ))
            else:
                # An active retailer with no rows today -- including one that has
                # never written a row at all (R1) -- is an outage, not a note (#7c).
                results.append(CheckResult(
                    f"today_coverage_{retailer}",
                    CheckResult.ERROR,
                    f"{retailer}: no snapshot for today ({today})",
                ))
```

Update the docstring's second paragraph to say that a missing retailer is an ERROR unless a cooldown explains it.

- [ ] **Step 6: Umart thresholds**

In `config.py`, replace `DEFAULT_MATCH_THRESHOLDS` with:

```python
# Expected match counts per retailer per scrape (multi-variant). Calibrated
# 11-Aug-2026 to ~194 Scorptec / ~41 PCCG matched variants at ~50% of
# baseline, to avoid false alarms from normal stock-level variation. Umart
# added 29-Sep-2026 from 31-Aug: 27 CPU + 155 GPU = 182 (#7, #15); the per-
# category floor is set by its small CPU side.
DEFAULT_MATCH_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "scorptec": {"min_total": 90, "min_per_category": 30},
    "pccg": {"min_total": 20, "min_per_category": 5},
    "umart": {"min_total": 90, "min_per_category": 10},
}
```

- [ ] **Step 7: The digest is blocked by a scraper problem (#7)**

In `run_daily.run`, change

```python
            if failed:
                LOGGER.warning("Skipping Discord digest - %d health check error(s).", len(failed))
            else:
```

to

```python
            if failed or scraper_lines:
                # A clean-looking digest over a failed or empty scrape is the
                # silent failure #7 describes.
                LOGGER.warning("Skipping Discord digest - %d health check error(s), %d scraper problem(s).",
                               len(failed), len(scraper_lines))
            else:
```

- [ ] **Step 8: Run the tests**

Run: `python -m pytest unit_testing/test_scrape_outcomes.py unit_testing/test_health_checks.py unit_testing/test_config.py unit_testing/test_umart_wiring.py unit_testing/test_run_daily_resilience.py unit_testing/test_pccg_query_budget.py unit_testing/test_pccg_reliability.py -q`

Expected: all PASS.

- [ ] **Step 9: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add scraper/run_report.py scraper/scorptec.py scraper/umart.py scraper/pccg.py run_daily.py health_checks.py config.py unit_testing/test_scrape_outcomes.py unit_testing/test_health_checks.py unit_testing/test_config.py
git commit -m "fix(pipeline): empty scrapes and missing retailers alert, cooldown skips only warn (#7)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The health strip lists every active retailer (R1)

**Files:**
- Create: `pipeline_state.py`
- Modify: `migrate.py` (add a table migration and call it in `main()`), `db/schema.sql` (append the table)
- Modify: `seed.py` (`main`), `run_daily.py` (sync inside the ingest block)
- Modify: `web/src/lib/server/repos.ts:413-433` (`RetailerFreshness`, `getRetailerFreshness`)
- Modify: `web/src/lib/health.ts:43` (`'no data'` -> `'missing'`)
- Modify: `web/e2e/seed.mjs:449` (seed the active retailers), `web/e2e/app.spec.ts:196-202`
- Test: `unit_testing/test_pipeline_state.py` (new), `unit_testing/test_migrate.py`, `web/test/repos.test.ts`, `web/test/health.test.ts:66-70`

**Interfaces:**
- Produces, in `migrate`: `ACTIVE_RETAILERS_TABLE_SQL: str` and `migrate_add_active_retailers_table(conn, dry_run=False) -> None`.
- Produces, in `pipeline_state`: `ensure_ops_tables(conn) -> None` and `sync_active_retailers(conn, retailers: Sequence[str]) -> None`.
- Produces, in web `repos.ts`: `tableExists(db: DB, name: string): boolean` (exported). `getRetailerFreshness(db)` returns every row in `active_retailers`, in `position` order, then any other retailer that has data, sorted by slug.

- [ ] **Step 1: Write the failing Python tests**

Create `unit_testing/test_pipeline_state.py`:

```python
"""Bookkeeping tables the pipeline and the dashboard share (R1, #8, R3)."""
import sqlite3

from config import ACTIVE_RETAILERS
from migrate import check_table_exists
from pipeline_state import ensure_ops_tables, sync_active_retailers


def _legacy(tmp_path):
    """A DB from before this phase: no bookkeeping tables at all."""
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
    return conn


class TestActiveRetailers:
    def test_sync_writes_the_config_list_in_order(self, db):
        sync_active_retailers(db, ACTIVE_RETAILERS)
        rows = db.execute("SELECT retailer FROM active_retailers ORDER BY position").fetchall()
        assert [r[0] for r in rows] == list(ACTIVE_RETAILERS)

    def test_sync_replaces_rather_than_appends(self, db):
        sync_active_retailers(db, ["scorptec", "pccg", "umart"])
        sync_active_retailers(db, ["scorptec", "umart"])
        rows = db.execute("SELECT retailer, position FROM active_retailers ORDER BY position").fetchall()
        assert [tuple(r) for r in rows] == [("scorptec", 0), ("umart", 1)]

    def test_works_on_a_db_that_predates_the_table(self, tmp_path):
        conn = _legacy(tmp_path)
        sync_active_retailers(conn, ["umart"])
        assert conn.execute("SELECT retailer FROM active_retailers").fetchall() == [("umart",)]

    def test_ensure_is_idempotent(self, tmp_path):
        conn = _legacy(tmp_path)
        ensure_ops_tables(conn)
        ensure_ops_tables(conn)
        assert check_table_exists(conn, "active_retailers")
```

Append to `unit_testing/test_migrate.py`, adding `migrate_add_active_retailers_table` to the `from migrate import (...)` block:

```python
class TestMigrateActiveRetailersTable:
    def test_creates_the_table(self, tmp_path):
        conn = get_connection(_make_legacy_db(tmp_path))
        try:
            migrate_add_active_retailers_table(conn)
            assert check_table_exists(conn, "active_retailers")
            migrate_add_active_retailers_table(conn)  # idempotent
        finally:
            conn.close()

    def test_dry_run_makes_no_change(self, tmp_path):
        conn = get_connection(_make_legacy_db(tmp_path))
        try:
            migrate_add_active_retailers_table(conn, dry_run=True)
            assert not check_table_exists(conn, "active_retailers")
        finally:
            conn.close()

    def test_schema_sql_creates_it_too(self, db):
        assert check_table_exists(db, "active_retailers")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_pipeline_state.py unit_testing/test_migrate.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline_state'` and `ImportError: cannot import name 'migrate_add_active_retailers_table'`.

- [ ] **Step 3: Table DDL in both places**

In `migrate.py`, after `migrate_add_price_alerts_table`, add:

```python
ACTIVE_RETAILERS_TABLE_SQL = """
CREATE TABLE active_retailers (
    retailer    TEXT    PRIMARY KEY,
    position    INTEGER NOT NULL
)
"""


def migrate_add_active_retailers_table(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create active_retailers (additive, create-if-missing).

    The dashboard reads it to list a retailer that has never written a row (R1).
    """
    if check_table_exists(conn, "active_retailers"):
        LOGGER.info("  [SKIP] active_retailers table already exists")
        return
    if dry_run:
        LOGGER.info("  [DRY-RUN] Would create active_retailers table")
        return
    LOGGER.info("  [MIGRATE] Creating active_retailers table...")
    conn.execute(ACTIVE_RETAILERS_TABLE_SQL)
    conn.commit()
    LOGGER.info("  [OK] active_retailers table created")
```

In `main()`, after `migrate_widen_retailer_check(conn, dry_run=args.dry_run)`, add:

```python
        # Migration: bookkeeping tables (Phase 3 robustness)
        migrate_add_active_retailers_table(conn, dry_run=args.dry_run)
```

Append to `db/schema.sql`:

```sql

-- ─────────────────────────────────────────────────────────────
-- active_retailers: the retailers the pipeline scrapes
-- (config.ACTIVE_RETAILERS), mirrored into the DB so the dashboard can list
-- one that has never written a row (R1). Rewritten by
-- pipeline_state.sync_active_retailers on every seed and daily run; never
-- edited by hand. Keep in step with migrate.ACTIVE_RETAILERS_TABLE_SQL.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE active_retailers (
    retailer    TEXT    PRIMARY KEY,
    position    INTEGER NOT NULL
);
```

- [ ] **Step 4: `pipeline_state.py`**

```python
"""Pipeline bookkeeping tables shared with the dashboard.

- active_retailers: which retailers the pipeline scrapes (R1).

Every helper calls ensure_ops_tables first, so a DB that has not been through
migrate.py yet (a native run straight after `git pull`) still works. The DDL
itself lives in migrate.py and db/schema.sql -- never here.
"""
from __future__ import annotations

import sqlite3
from typing import Sequence

from migrate import check_table_exists, migrate_add_active_retailers_table


def ensure_ops_tables(conn: sqlite3.Connection) -> None:
    """Create any missing bookkeeping table. Idempotent and quiet when present."""
    if not check_table_exists(conn, "active_retailers"):
        migrate_add_active_retailers_table(conn)


def sync_active_retailers(conn: sqlite3.Connection, retailers: Sequence[str]) -> None:
    """Make active_retailers hold exactly ``retailers``, in order.

    Only the bookkeeping rows are replaced; no price data is touched.
    """
    ensure_ops_tables(conn)
    conn.execute("DELETE FROM active_retailers")
    conn.executemany(
        "INSERT INTO active_retailers (retailer, position) VALUES (?, ?)",
        [(r, i) for i, r in enumerate(retailers)],
    )
    conn.commit()
```

- [ ] **Step 5: Keep the table in sync**

In `seed.py`:
- Change the config import to `from config import ACTIVE_RETAILERS, DB_PATH, SCHEMA_PATH, WATCHLIST_PATH`.
- Add `from pipeline_state import sync_active_retailers`.
- In `main()`, right after `stats = seed_products(conn, products, dry_run=args.dry_run)`, add:

```python
    # The container runs seed.py on every boot, so this keeps the dashboard's
    # retailer list (active_retailers) equal to config even before the first
    # daily run on a new build (R1).
    if not args.dry_run:
        sync_active_retailers(conn, ACTIVE_RETAILERS)
```

In `run_daily.py`:
- Add `from pipeline_state import sync_active_retailers`.
- In `run()`, directly after `conn = init_db(DB_PATH)` and its `try:`, before `stats = ingest_today(...)`, add:

```python
            if not args.dry_run:
                best_effort("Active-retailer sync", sync_active_retailers, conn, ACTIVE_RETAILERS)
```

- [ ] **Step 6: Run the Python tests**

Run: `python -m pytest unit_testing/test_pipeline_state.py unit_testing/test_migrate.py unit_testing/test_seed.py unit_testing/test_cli.py -q`

Expected: all PASS.

- [ ] **Step 7: Write the failing web tests**

Append to `web/test/repos.test.ts`, adding `tableExists` to the repos import:

```ts
describe('getRetailerFreshness lists every active retailer (R1)', () => {
	function freshnessDb(withActive: boolean) {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-fresh-'));
		const d = openDatabase(path.join(dir, 'f.db'), { readonly: false, fileMustExist: false });
		d.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
		if (!withActive) d.exec('DROP TABLE active_retailers');
		else
			d.exec(
				"INSERT INTO active_retailers (retailer, position) VALUES ('scorptec', 0), ('pccg', 1), ('umart', 2)"
			);
		d.exec(`INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Ryzen 5 5600', 1);
			INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x/1', 'active');
			INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'mwave', 'https://x/2', 'active');
			INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, '2026-09-28', 199, 'in_stock');
			INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (2, '2026-08-01', 210, 'in_stock');`);
		return {
			d,
			close: () => {
				d.close();
				fs.rmSync(dir, { recursive: true, force: true });
			}
		};
	}

	it('lists active retailers in config order, with null for one that never reported', () => {
		const { d, close } = freshnessDb(true);
		try {
			expect(getRetailerFreshness(d).map((r) => [r.retailer, r.latestSnapshotDate])).toEqual([
				['scorptec', '2026-09-28'],
				['pccg', null],
				['umart', null],
				// no longer active, but its history is real -- still shown, after the active ones
				['mwave', '2026-08-01']
			]);
		} finally {
			close();
		}
	});

	it('falls back to retailers with data when active_retailers is missing', () => {
		const { d, close } = freshnessDb(false);
		try {
			expect(tableExists(d, 'active_retailers')).toBe(false);
			expect(getRetailerFreshness(d).map((r) => r.retailer)).toEqual(['mwave', 'scorptec']);
		} finally {
			close();
		}
	});
});
```

(`fs`, `os`, `path`, `openDatabase` and `SCHEMA_PATH` are already imported in that file; `createCoverageDb` uses them.)

In `web/test/health.test.ts`, change the last test's expectation from `'no data'` to `'missing'`, and rename it `'reports an active retailer that has never reported as missing'`.

In `web/e2e/app.spec.ts`, extend the health-strip test (`:196-202`):

```ts
	test('shows a data-health strip naming each retailer and its age', async ({ page }) => {
		await goto(page, '/');
		const strip = page.getByLabel('Data health');
		await expect(strip).toBeVisible();
		await expect(strip.getByText('Scorptec')).toBeVisible();
		await expect(strip.getByText('PCCG')).toBeVisible();
		// e2e/seed.mjs declares MWave active with no rows: it must be listed, not hidden (R1).
		await expect(strip.getByText('MWave')).toBeVisible();
		await expect(strip.getByText('missing').first()).toBeVisible();
	});
```

- [ ] **Step 8: Run to verify they fail**

Run (from `web/`): `npm test -- repos health`

Expected: FAIL. `tableExists` is not exported, `pccg`/`umart` are absent from the list, and the text is still `'no data'`.

- [ ] **Step 9: Implement the web side**

In `web/src/lib/server/repos.ts`, replace the `RetailerFreshness` block (`:413-433`) with:

```ts
export interface RetailerFreshness {
	retailer: Retailer;
	latestSnapshotDate: string | null;
}

// True when `name` is a table in this DB. The dashboard must keep rendering on a
// DB from before a migration ran (Review Focus 5).
export function tableExists(db: DB, name: string): boolean {
	return (
		db.prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?").get(name) !==
		undefined
	);
}

// Per-retailer currency for the homepage health strip and /healthz.
// The retailer list comes from active_retailers -- the pipeline's
// config.ACTIVE_RETAILERS mirrored into the DB -- so a retailer that has never
// written a row is listed as missing instead of silently absent (R1, 28-Sep:
// Umart on prod). A retailer that is no longer active but has history follows,
// by slug. On a DB without the table, retailers with data are listed by slug.
export function getRetailerFreshness(db: DB): RetailerFreshness[] {
	const latest = db
		.prepare(
			`SELECT l.retailer AS retailer, MAX(s.snapshot_date) AS latest
			 FROM retailer_listings l
			 JOIN price_snapshots s ON s.retailer_listing_id = l.id
			 GROUP BY l.retailer`
		)
		.all() as Array<{ retailer: string; latest: string | null }>;
	const latestBy = new Map(latest.map((r) => [r.retailer, r.latest]));

	const active = tableExists(db, 'active_retailers')
		? (
				db
					.prepare('SELECT retailer FROM active_retailers ORDER BY position, retailer')
					.all() as Array<{ retailer: string }>
			).map((r) => r.retailer)
		: [];
	const inactive = [...latestBy.keys()].filter((r) => !active.includes(r)).sort();

	return [...active, ...inactive].map((retailer) => ({
		retailer: retailer as Retailer,
		latestSnapshotDate: latestBy.get(retailer) ?? null
	}));
}
```

In `web/src/lib/health.ts:43`, change `'no data'` to `'missing'`.

In `web/e2e/seed.mjs`, directly before the final `db.close();` of `seedE2eDb` (`:449`), add:

```js
	// The pipeline mirrors config.ACTIVE_RETAILERS into this table (R1). MWave is
	// declared active here with no rows on purpose: the health strip must list
	// it as "missing" in both the synthetic and the real-data seed.
	const activeRetailer = db.prepare(
		'INSERT INTO active_retailers (retailer, position) VALUES (?, ?)'
	);
	['scorptec', 'pccg', 'umart', 'mwave'].forEach((r, i) => activeRetailer.run(r, i));
```

- [ ] **Step 10: Run the web tests**

Run (from `web/`): `npm test -- repos health` and then `npm run test:e2e`

Expected: all PASS.

- [ ] **Step 11: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add pipeline_state.py migrate.py db/schema.sql seed.py run_daily.py unit_testing/test_pipeline_state.py unit_testing/test_migrate.py web/src/lib/server/repos.ts web/src/lib/health.ts web/e2e/seed.mjs web/e2e/app.spec.ts web/test/repos.test.ts web/test/health.test.ts
git commit -m "feat(health): every active retailer shows on the health strip, 'missing' when it never reported (R1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Hourly per-retailer retry until a cutoff; the staleness alert fires the same day (#8)

**Files:**
- Modify: `migrate.py`, `db/schema.sql` (`scrape_runs`, `run_markers`)
- Modify: `pipeline_state.py` (`record_scrape_run`, `retailers_pending`, `claim_marker`, extend `ensure_ops_tables`)
- Modify: `config.py` (`RUN_AT_HOUR`, `RETRY_UNTIL_HOUR`)
- Modify: `run_daily.py` (flags, window, pending, record, `claim_once`, alert dedupe, digest once)
- Modify: `deploy/entrypoint-single.sh`, `deploy/entrypoint.sh` (delegate to `--scheduled` / `--pending-only`)
- Modify: `check_staleness.py:43-51, 118-168`
- Modify: `unit_testing/test_check_staleness.py`
- Create: `unit_testing/test_retry.py`

**Interfaces:**
- Consumes: `ScrapeOutcome`, `run`, `send_pipeline_alert`, `isolated_pipeline` (Task 1); `ensure_ops_tables` (Task 3); `cooldown_explains` (Task 2).
- Produces, in `pipeline_state`:
  - `record_scrape_run(conn, *, retailer: str, run_date: str, started_at: str, finished_at: str, status: str, exit_code: Optional[int] = None, matched: Optional[int] = None, detail: Optional[str] = None) -> None` (does not commit)
  - `retailers_pending(conn, run_date: str, retailers: Sequence[str]) -> List[str]`
  - `claim_marker(conn, name: str, run_date: str) -> bool` (commits)
- Produces, in `run_daily`:
  - `in_retry_window(hour: int, run_at: int, until: int) -> bool`
  - `_current_hour() -> int`
  - `pending_retailers(candidates: Sequence[str], run_date: str) -> List[str]`
  - `record_outcomes(outcomes: List[ScrapeOutcome], run_date: str) -> None`
  - `claim_once(name: str) -> bool`
  - the CLI flags `--pending-only` and `--scheduled`
- Produces, in `config`: `RUN_AT_HOUR: int = 4` and `RETRY_UNTIL_HOUR: int = 9`, read from the env vars of the same names.
- Produces, in `check_staleness`: `DEFAULT_THRESHOLD_DAYS = 0`.

- [ ] **Step 1: Write the failing tests**

Create `unit_testing/test_retry.py`:

```python
"""Per-retailer hourly retry until a cutoff (#8)."""
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import run_daily
from config import ACTIVE_RETAILERS
from pipeline_state import claim_marker, record_scrape_run, retailers_pending
from scraper.snapshot_io import build_snapshot, save_snapshot

TODAY = date.today().isoformat()
REPO = Path(__file__).resolve().parent.parent


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


def _record(conn, retailer, status, run_date=TODAY):
    record_scrape_run(conn, retailer=retailer, run_date=run_date, started_at=f"{run_date}T04:00:00",
                      finished_at=f"{run_date}T04:05:00", status=status)
    conn.commit()


class TestRetailersPending:
    def test_no_run_and_no_data_is_pending(self, db):
        assert retailers_pending(db, TODAY, ["scorptec", "pccg"]) == ["scorptec", "pccg"]

    @pytest.mark.parametrize("status", ["degraded", "skipped", "auth", "failed", "timeout"])
    def test_a_latest_run_that_is_not_ok_is_pending(self, db, status):
        _record(db, "pccg", status)
        assert retailers_pending(db, TODAY, ["pccg"]) == ["pccg"]

    def test_only_the_latest_run_counts(self, db):
        _record(db, "pccg", "failed")
        _record(db, "pccg", "ok")
        assert retailers_pending(db, TODAY, ["pccg"]) == []

    def test_yesterdays_ok_does_not_count_today(self, db):
        _record(db, "pccg", "ok", run_date="2000-01-01")
        assert retailers_pending(db, TODAY, ["pccg"]) == ["pccg"]

    def test_pre_upgrade_day_with_snapshots_is_not_pending(self, db):
        """Review Focus 3: the deploy day must not re-scrape what the old build already got."""
        db.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'X', 1)")
        db.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                   "VALUES (1, 'scorptec', 'https://x/1', 'active')")
        db.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                   "VALUES (1, ?, 100, 'in_stock')", (TODAY,))
        assert retailers_pending(db, TODAY, ["scorptec", "pccg"]) == ["pccg"]

    @pytest.mark.parametrize("status", run_daily.SCRAPE_STATUSES)
    def test_every_outcome_status_is_accepted_by_the_table(self, db, status):
        _record(db, "umart", status)


class TestClaimMarker:
    def test_first_claim_wins_per_day(self, db):
        assert claim_marker(db, "digest", TODAY) is True
        assert claim_marker(db, "digest", TODAY) is False
        assert claim_marker(db, "digest", "2000-01-01") is True


class TestRetryWindow:
    @pytest.mark.parametrize("hour,expected", [(3, False), (4, True), (7, True), (9, True), (10, False)])
    def test_window(self, hour, expected):
        assert run_daily.in_retry_window(hour, 4, 9) is expected

    def test_a_cutoff_before_the_run_hour_still_runs_once(self):
        assert run_daily.in_retry_window(4, 4, 2) is True
        assert run_daily.in_retry_window(5, 4, 2) is False


def _writing_scraper(data_dir, fail_first):
    """A fake scraper that writes a real one-product snapshot when it succeeds."""
    attempts = []

    def scraper(name, module, label):
        attempts.append(label)
        if label in fail_first and attempts.count(label) == 1:
            return run_daily.ScrapeOutcome(label, "failed", 1)
        stamp = run_daily.today_filename()
        product = {
            "watchlist_model": "Ryzen 7 9800X3D", "watchlist_category": "cpu",
            "watchlist_brand": "AMD", "watchlist_gen_tier": "current", "retailer": label,
            "price_aud": 599.0, "stock_status": "in_stock",
            "url": f"https://www.{label}.example/product/cpu/{len(attempts)}",
        }
        save_snapshot(data_dir / f"cpu_{label}_{stamp}.json",
                      build_snapshot(label, stamp, "cpu", 1, [product], []))
        return run_daily.ScrapeOutcome(label, "ok", 0)

    return scraper, attempts


class TestRetryEndToEnd:
    def test_pccg_fails_at_4_and_succeeds_at_5(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first={"pccg"})
        monkeypatch.setattr(run_daily, "run_scraper", scraper)

        run_daily.run(_args())                               # 04:00
        assert run_daily.pending_retailers(list(ACTIVE_RETAILERS), TODAY) == ["pccg"]

        run_daily.run(_args("--pending-only"))               # 05:00
        assert attempts == ["scorptec", "pccg", "umart", "pccg"]
        assert run_daily.pending_retailers(list(ACTIVE_RETAILERS), TODAY) == []

        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        pccg_rows = conn.execute(
            "SELECT COUNT(*) FROM price_snapshots ps JOIN retailer_listings rl ON rl.id = ps.retailer_listing_id "
            "WHERE rl.retailer = 'pccg' AND ps.snapshot_date = ?", (TODAY,)).fetchone()[0]
        conn.close()
        assert pccg_rows == 1

    def test_nothing_pending_means_no_scrape(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        run_daily.run(_args())
        attempts.clear()

        assert run_daily.run(_args("--pending-only")) == run_daily.RUN_EXIT_OK
        assert attempts == []

    def test_scheduled_does_nothing_after_the_cutoff(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        monkeypatch.setattr(run_daily, "_current_hour", lambda: run_daily.RETRY_UNTIL_HOUR + 1)

        assert run_daily.run(_args("--scheduled")) == run_daily.RUN_EXIT_OK
        assert attempts == []

    def test_scheduled_retries_inside_the_window(self, isolated_pipeline, monkeypatch):
        scraper, attempts = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        monkeypatch.setattr(run_daily, "_current_hour", lambda: run_daily.RUN_AT_HOUR)

        run_daily.run(_args("--scheduled"))
        assert attempts == list(ACTIVE_RETAILERS)


class TestOncePerDay:
    """Review Focus 2: hourly retries must not repeat the digest or an identical alert."""

    def test_the_digest_is_sent_once_a_day(self, isolated_pipeline, monkeypatch):
        scraper, _ = _writing_scraper(isolated_pipeline.data_dir, fail_first=set())
        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        run_daily.run(_args())
        run_daily.run(_args())
        assert isolated_pipeline.digests == 1

    def test_an_identical_alert_is_sent_once_a_day(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        run_daily.run(_args())
        # --pccg too, so the retry is not the all-failed path (a different alert).
        run_daily.run(_args("--pccg", "--umart"))
        assert len(isolated_pipeline.alerts) == 1


def test_entrypoints_delegate_the_schedule_to_run_daily():
    for name in ("entrypoint-single.sh", "entrypoint.sh"):
        text = (REPO / "deploy" / name).read_text(encoding="utf-8")
        assert "todays_run_done" not in text, name
        assert "run_pipeline --pending-only" in text, name
        assert "run_pipeline --scheduled" in text, name
        assert "export RUN_AT_HOUR RETRY_UNTIL_HOUR" in text, name
```

In `unit_testing/test_check_staleness.py`:

Add an autouse fixture after the imports, so a real `data/pccg_cooldown.json` on the dev machine cannot flip a result:

```python
@pytest.fixture(autouse=True)
def _no_cooldown(monkeypatch):
    monkeypatch.setattr(check_staleness, "cooldown_explains", lambda retailer: False)
```

Replace `test_yesterdays_data_is_tolerated_at_default_threshold` with:

```python
def test_no_data_today_is_an_error_by_the_check_hour(tmp_path):
    """#8: the monitor runs at STALENESS_CHECK_HOUR, after the retry cutoff --
    by then a day without data is an outage, not 'not yet'."""
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-26"), ("pccg", "2026-08-26"),
                             ("umart", "2026-08-26")])

    results = check_staleness.evaluate(db_path=db, today=today)

    assert _statuses(results)["snapshot_staleness"] == CheckResult.ERROR
```

In `test_threshold_is_configurable`, change the DB to `_make_db(tmp_path, [("scorptec", "2026-08-25"), ("pccg", "2026-08-25"), ("umart", "2026-08-25")])`.

Replace `test_one_lagging_retailer_warns_but_does_not_error` with:

```python
def test_a_lagging_retailer_is_an_error(tmp_path):
    """#8: page on any single retailer missing today."""
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-27"), ("pccg", "2026-08-22"), ("umart", "2026-08-27")])

    results = check_staleness.evaluate(db_path=db, today=today)

    assert _statuses(results)["retailer_staleness_pccg"] == CheckResult.ERROR
    assert _statuses(results)["snapshot_staleness"] == CheckResult.OK


def test_a_cooling_down_retailer_only_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(check_staleness, "cooldown_explains", lambda retailer: retailer == "pccg")
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-27"), ("pccg", "2026-08-22"), ("umart", "2026-08-27")])

    results = check_staleness.evaluate(db_path=db, today=today)

    assert _worst(results) == CheckResult.WARNING


def test_a_retailer_that_never_reported_is_an_error(tmp_path):
    """R1: Umart had no rows on prod and nothing alerted."""
    today = date(2026, 8, 27)
    db = _make_db(tmp_path, [("scorptec", "2026-08-27"), ("pccg", "2026-08-27")])

    assert _statuses(check_staleness.evaluate(db_path=db, today=today))["retailer_staleness_umart"] == CheckResult.ERROR
```

In `test_run_returns_zero_and_stays_quiet_when_fresh`, add `("umart", "2026-08-27")` to the DB.

Replace `test_warnings_alone_do_not_alert_or_fail` with:

```python
def test_warnings_alone_do_not_alert_or_fail(tmp_path, monkeypatch):
    """A cooling-down retailer is reported, but must not page anyone."""
    sent = []
    monkeypatch.setattr(check_staleness, "send_alert", lambda lines, dry_run=False: sent.append(lines) or 1)
    monkeypatch.setattr(check_staleness, "cooldown_explains", lambda retailer: retailer == "pccg")
    db = _make_db(tmp_path, [("scorptec", "2026-08-27"), ("pccg", "2026-08-20"), ("umart", "2026-08-27")])

    code = check_staleness.run(db_path=str(db), today=date(2026, 8, 27))

    assert code == 0
    assert not sent
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_retry.py unit_testing/test_check_staleness.py -q`

Expected: FAIL with `ImportError: cannot import name 'claim_marker'`, then staleness assertion failures.

- [ ] **Step 3: DDL for `scrape_runs` and `run_markers`**

In `migrate.py`, after `migrate_add_active_retailers_table`, add:

```python
SCRAPE_RUNS_TABLE_SQL = """
CREATE TABLE scrape_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer     TEXT    NOT NULL,
    run_date     TEXT    NOT NULL,   -- YYYY-MM-DD, local: the snapshot_date calendar
    started_at   TEXT    NOT NULL,   -- local 'YYYY-MM-DDTHH:MM:SS'
    finished_at  TEXT    NOT NULL,
    status       TEXT    NOT NULL
                 CHECK (status IN ('ok', 'degraded', 'skipped', 'auth', 'failed', 'timeout')),
    exit_code    INTEGER,
    matched      INTEGER,            -- products matched this run; NULL when unknown
    detail       TEXT
)
"""

RUN_MARKERS_TABLE_SQL = """
CREATE TABLE run_markers (
    name        TEXT    NOT NULL,
    run_date    TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (name, run_date)
)
"""


def migrate_add_scrape_runs_table(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create scrape_runs: one row per scraper run (#8 retry state, R3 freshness)."""
    if check_table_exists(conn, "scrape_runs"):
        LOGGER.info("  [SKIP] scrape_runs table already exists")
        return
    if dry_run:
        LOGGER.info("  [DRY-RUN] Would create scrape_runs table")
        return
    LOGGER.info("  [MIGRATE] Creating scrape_runs table...")
    conn.execute(SCRAPE_RUNS_TABLE_SQL)
    conn.execute("CREATE INDEX idx_scrape_runs_retailer_date ON scrape_runs (retailer, run_date)")
    conn.commit()
    LOGGER.info("  [OK] scrape_runs table created")


def migrate_add_run_markers_table(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create run_markers: once-per-day claims (digest, identical alerts) (#8)."""
    if check_table_exists(conn, "run_markers"):
        LOGGER.info("  [SKIP] run_markers table already exists")
        return
    if dry_run:
        LOGGER.info("  [DRY-RUN] Would create run_markers table")
        return
    LOGGER.info("  [MIGRATE] Creating run_markers table...")
    conn.execute(RUN_MARKERS_TABLE_SQL)
    conn.commit()
    LOGGER.info("  [OK] run_markers table created")
```

In `main()`, after the active-retailers migration call, add:

```python
        migrate_add_scrape_runs_table(conn, dry_run=args.dry_run)
        migrate_add_run_markers_table(conn, dry_run=args.dry_run)
```

Append to `db/schema.sql`:

```sql

-- ─────────────────────────────────────────────────────────────
-- scrape_runs: one row per scraper subprocess run, written by run_daily.py.
-- Drives the hourly per-retailer retry (#8: a retailer is done today once its
-- latest run today is 'ok') and the health strip's "today 04:12, 312 matched"
-- (R3). Keep in step with migrate.SCRAPE_RUNS_TABLE_SQL.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE scrape_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer     TEXT    NOT NULL,
    run_date     TEXT    NOT NULL,   -- YYYY-MM-DD, local: the snapshot_date calendar
    started_at   TEXT    NOT NULL,   -- local 'YYYY-MM-DDTHH:MM:SS'
    finished_at  TEXT    NOT NULL,
    status       TEXT    NOT NULL
                 CHECK (status IN ('ok', 'degraded', 'skipped', 'auth', 'failed', 'timeout')),
    exit_code    INTEGER,
    matched      INTEGER,            -- products matched this run; NULL when unknown
    detail       TEXT
);

CREATE INDEX idx_scrape_runs_retailer_date ON scrape_runs (retailer, run_date);

-- ─────────────────────────────────────────────────────────────
-- run_markers: once-per-day claims, so hourly retries do not repeat the
-- Discord digest or an identical pipeline alert (#8).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE run_markers (
    name        TEXT    NOT NULL,
    run_date    TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (name, run_date)
);
```

Add to `unit_testing/test_migrate.py` (and add the two functions to its import block):

```python
class TestMigrateRetryTables:
    def test_creates_both_and_is_idempotent(self, tmp_path):
        conn = get_connection(_make_legacy_db(tmp_path))
        try:
            for _ in range(2):
                migrate_add_scrape_runs_table(conn)
                migrate_add_run_markers_table(conn)
            assert check_table_exists(conn, "scrape_runs")
            assert check_table_exists(conn, "run_markers")
        finally:
            conn.close()
```

- [ ] **Step 4: `pipeline_state.py` additions**

Update the module docstring's list:

```python
- scrape_runs: one row per scraper run (#8 retry state, R3 freshness).
- run_markers: once-per-day claims (#8: no repeated digest or alert).
```

Change the import to:

```python
from typing import List, Optional, Sequence

from migrate import (
    check_table_exists,
    migrate_add_active_retailers_table,
    migrate_add_run_markers_table,
    migrate_add_scrape_runs_table,
)
```

Replace `ensure_ops_tables` and append the new helpers:

```python
def ensure_ops_tables(conn: sqlite3.Connection) -> None:
    """Create any missing bookkeeping table. Idempotent and quiet when present."""
    for table, create in (
        ("active_retailers", migrate_add_active_retailers_table),
        ("scrape_runs", migrate_add_scrape_runs_table),
        ("run_markers", migrate_add_run_markers_table),
    ):
        if not check_table_exists(conn, table):
            create(conn)


def record_scrape_run(
    conn: sqlite3.Connection,
    *,
    retailer: str,
    run_date: str,
    started_at: str,
    finished_at: str,
    status: str,
    exit_code: Optional[int] = None,
    matched: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    """Append one scrape_runs row. The caller commits."""
    ensure_ops_tables(conn)
    conn.execute(
        "INSERT INTO scrape_runs (retailer, run_date, started_at, finished_at, status, "
        "exit_code, matched, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (retailer, run_date, started_at, finished_at, status, exit_code, matched, detail),
    )


def retailers_pending(conn: sqlite3.Connection, run_date: str, retailers: Sequence[str]) -> List[str]:
    """Retailers that still need a scrape on ``run_date`` (#8), in the given order.

    A retailer is done when its latest scrape_runs row for the day is 'ok'.
    Any other latest status -- degraded, skipped, auth, failed, timeout --
    leaves it pending. With no row for the day, it is done only if it already
    has snapshots for the day: that is the day a build without scrape_runs
    did the scraping (the Phase 6 deploy day), and re-scraping it would only
    spend retailer goodwill (Review Focus 3).
    """
    ensure_ops_tables(conn)
    pending: List[str] = []
    for retailer in retailers:
        row = conn.execute(
            "SELECT status FROM scrape_runs WHERE retailer = ? AND run_date = ? "
            "ORDER BY id DESC LIMIT 1",
            (retailer, run_date),
        ).fetchone()
        if row is not None:
            if row[0] != "ok":
                pending.append(retailer)
            continue
        has_data = conn.execute(
            "SELECT 1 FROM price_snapshots ps "
            "JOIN retailer_listings rl ON rl.id = ps.retailer_listing_id "
            "WHERE rl.retailer = ? AND ps.snapshot_date = ? LIMIT 1",
            (retailer, run_date),
        ).fetchone()
        if not has_data:
            pending.append(retailer)
    return pending


def claim_marker(conn: sqlite3.Connection, name: str, run_date: str) -> bool:
    """Claim ``name`` for ``run_date``. True only the first time that day."""
    ensure_ops_tables(conn)
    cur = conn.execute(
        "INSERT OR IGNORE INTO run_markers (name, run_date) VALUES (?, ?)", (name, run_date)
    )
    conn.commit()
    return cur.rowcount == 1
```

- [ ] **Step 5: Config**

In `config.py`, after `SCRAPER_GAP_SECONDS`, add:

```python
# ── Scheduling (deploy/entrypoint*.sh -> run_daily.py --scheduled) ─────
# Same env names the entrypoints always used (no TRACKAROO_ prefix), so one
# setting drives both. The daily run starts at RUN_AT_HOUR; a retailer that
# failed or came back incomplete is retried hourly up to and including
# RETRY_UNTIL_HOUR (#8). Keep RETRY_UNTIL_HOUR < STALENESS_CHECK_HOUR (10) so
# the staleness monitor judges a finished day.
RUN_AT_HOUR = _env_int("RUN_AT_HOUR", 4)
RETRY_UNTIL_HOUR = _env_int("RETRY_UNTIL_HOUR", 9)
```

Add both to the module docstring's env list:

```
    RUN_AT_HOUR                         Daily run hour, local 0-23      (default: 4)
    RETRY_UNTIL_HOUR                    Last hourly retry, local 0-23   (default: 9)
```

- [ ] **Step 6: `run_daily.py`**

- Add `import hashlib` to the stdlib imports.
- Add `RETRY_UNTIL_HOUR, RUN_AT_HOUR` to the config import.
- Change the pipeline_state import to:

```python
from pipeline_state import (
    claim_marker,
    ensure_ops_tables,
    record_scrape_run,
    retailers_pending,
    sync_active_retailers,
)
```

In `build_parser()`, after `--no-backup`, add:

```python
    parser.add_argument("--pending-only", action="store_true",
                        help="Only scrape retailers without a complete run today (boot catch-up)")
    parser.add_argument("--scheduled", action="store_true",
                        help="Hourly scheduler entry: --pending-only, and a no-op outside "
                             "RUN_AT_HOUR..RETRY_UNTIL_HOUR")
```

After `run_db_checks`, add:

```python
def _current_hour() -> int:
    return datetime.now().hour


def in_retry_window(hour: int, run_at: int, until: int) -> bool:
    """True when ``hour`` is inside RUN_AT_HOUR..RETRY_UNTIL_HOUR, inclusive (#8).

    A cutoff before the run hour (misconfiguration) degrades to "the run hour
    only", never to "never".
    """
    if until < run_at:
        return hour == run_at
    return run_at <= hour <= until


def pending_retailers(candidates: Sequence[str], run_date: str) -> List[str]:
    """Which of ``candidates`` still need a scrape today. If the state cannot be
    read, scrape them all: a wasted scrape beats a lost day."""
    try:
        conn = init_db(DB_PATH)
        try:
            return retailers_pending(conn, run_date, candidates)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        LOGGER.exception("Could not read today's run state - scraping every selected retailer")
        return list(candidates)


def record_outcomes(outcomes: List[ScrapeOutcome], run_date: str) -> None:
    """Persist this run's outcomes to scrape_runs (#8, R3)."""
    conn = init_db(DB_PATH)
    try:
        for o in outcomes:
            record_scrape_run(
                conn, retailer=o.retailer, run_date=run_date,
                started_at=o.started_at or _now(), finished_at=o.finished_at or _now(),
                status=o.status, exit_code=o.exit_code, matched=o.matched,
                detail=o.detail or None,
            )
        conn.commit()
    finally:
        conn.close()


def claim_once(name: str) -> bool:
    """True the first time ``name`` is claimed today.

    Hourly retries (#8) must not repeat the digest or an identical alert. This
    errs towards True: a broken state table must never silence an alert.
    """
    try:
        conn = init_db(DB_PATH)
        try:
            return claim_marker(conn, name, date.today().isoformat())
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        LOGGER.exception("Could not read run markers - sending anyway")
        return True
```

(`Sequence` joins the typing import: `from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple`.)

Replace `send_pipeline_alert` with:

```python
def send_pipeline_alert(lines: List[str]) -> None:
    """Post a pipeline-issue alert to DISCORD_WEBHOOK_ALERT; never raises.

    An alert identical to one already sent today is not repeated: an hourly
    retry that fails the same way would otherwise post it up to 6 times (#8).
    """
    key = "alert:" + hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()[:16]
    if not claim_once(key):
        LOGGER.info("The same pipeline alert was already sent today - not repeating it.")
        return
    from notify_discord import send_alert
    best_effort("Pipeline alert", send_alert, lines)
```

In `run()`, replace the first line `to_run = selected_retailers(args)` with:

```python
    to_run = selected_retailers(args)
    today_iso = date.today().isoformat()

    # ── What is left to do today (#8) ─────────────────────────
    if args.scheduled and not in_retry_window(_current_hour(), RUN_AT_HOUR, RETRY_UNTIL_HOUR):
        LOGGER.info("Outside the run window (%02d:00-%02d:59) - nothing to do.",
                    RUN_AT_HOUR, RETRY_UNTIL_HOUR)
        return RUN_EXIT_OK
    if args.pending_only or args.scheduled:
        to_run = pending_retailers(to_run, today_iso)
        if not to_run:
            LOGGER.info("Every selected retailer already has a complete run today - nothing to do.")
            return RUN_EXIT_OK
```

Directly after the scrape-summary `for` loop (before `scraper_lines = ...`), add:

```python
    if not args.dry_run:
        best_effort("Recording scrape runs", record_outcomes, list(results.values()), today_iso)
```

In the digest block, replace

```python
            else:
                from notify_discord import run as run_notify
                best_effort("Discord digest", run_notify)
```

with

```python
            elif not claim_once("digest"):
                LOGGER.info("Discord digest already sent today - not repeating it.")
            else:
                from notify_discord import run as run_notify
                best_effort("Discord digest", run_notify)
```

- [ ] **Step 7: Entrypoints delegate to `run_daily`**

In `deploy/entrypoint-single.sh`:

(a) In the header "Knobs (env)" list, after `RUN_AT_HOUR`, add:

```sh
#   RETRY_UNTIL_HOUR     Last local hour (0-23, default 9) at which a retailer that
#                        failed or came back incomplete today is retried. Retries
#                        run hourly from RUN_AT_HOUR. Keep it EARLIER than
#                        STALENESS_CHECK_HOUR so the monitor judges a finished day.
```

(b) Replace `: "${RUN_AT_HOUR:=4}"` with:

```sh
: "${RUN_AT_HOUR:=4}"
: "${RETRY_UNTIL_HOUR:=9}"
# run_daily.py reads both (config.py), so export the defaults too.
export RUN_AT_HOUR RETRY_UNTIL_HOUR
```

(c) Replace `run_pipeline()` (`:62-65`) with:

```sh
# run_daily.py decides what is left to do (#8): --pending-only scrapes only the
# retailers without a complete run today; --scheduled additionally does
# nothing outside RUN_AT_HOUR..RETRY_UNTIL_HOUR. Both are no-ops once every
# retailer is done, so calling them hourly is cheap and restart-safe.
run_pipeline() {
    log "Starting pipeline $*..."
    python run_daily.py "$@" && log "Pipeline finished." || log "Pipeline finished with errors (failed retailers retry hourly until ${RETRY_UNTIL_HOUR}:59)."
}
```

(d) Delete the whole `todays_run_done()` function and its comment (`:81-106`).

(e) Replace the catch-up block (`:171-179`) with:

```sh
# Catch-up: if the container was down over the run hour, whatever today is
# still missing would be lost permanently (retailers only expose current
# prices). Scrape only that, whatever the hour.
run_pipeline --pending-only
```

(f) Replace the scheduler log line and loop body (`:181-202`) with:

```sh
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
```

The `RUN_ONCE` branch keeps calling `run_pipeline` with no arguments: a full run.

In `deploy/entrypoint.sh`, make the same changes:
- Add the `RETRY_UNTIL_HOUR` knob comment.
- Add the `: "${RETRY_UNTIL_HOUR:=9}"` default and `export RUN_AT_HOUR RETRY_UNTIL_HOUR`.
- Replace `run_pipeline` with the same function.
- Delete `todays_run_done`.
- Make the catch-up `run_pipeline --pending-only`.
- Change the loop to:

```sh
log "Trackaroo scheduler started (daily at ${RUN_AT_HOUR_PAD}:00 ${TZ:-local}, failed retailers retried hourly until ${RETRY_UNTIL_HOUR}:59)"
while true; do
    sleep 3600
    run_pipeline --scheduled
done
```

Check line endings (CLAUDE.md, no grep): `python -c "import sys;[print(f, open(f,'rb').read().count(bytes([13]))) for f in sys.argv[1:]]" deploy/entrypoint-single.sh deploy/entrypoint.sh`

Expected: both `0`.

- [ ] **Step 8: Staleness: threshold 0, and per-retailer ERROR**

In `check_staleness.py`:

Update the severity paragraph of the module docstring to:

```
Severity (29-Sep-2026, #8):

- **ERROR** -- nothing in the DB, the DB is missing/unreadable, the newest
  snapshot is older than today, or any active retailer has nothing today
  (including one that has never reported, R1). The monitor runs at
  STALENESS_CHECK_HOUR, after the last retry (RETRY_UNTIL_HOUR), so by then a
  missing day is an outage, not "not yet".
- **WARNING** -- a retailer missing today while its scraper cooldown is
  active (PCCG's circuit breaker): expected, reported, never paged.
```

Change the import to `from health_checks import CheckResult, cooldown_explains`.

Replace the threshold block (`:43-45`) with:

```python
# The monitor runs at STALENESS_CHECK_HOUR (10), after the last hourly retry
# (RETRY_UNTIL_HOUR, 9). By then anything older than today means the day was
# missed. The old default of 1 read yesterday's data as fresh at 10:00 and only
# alerted on day 2 (#8).
DEFAULT_THRESHOLD_DAYS = 0
```

Replace the per-retailer loop body (`:145-168`) with:

```python
        seen = {r["retailer"]: r["last_date"] for r in rows}
        for retailer in EXPECTED_RETAILERS:
            name = f"retailer_staleness_{retailer}"
            try:
                r_last = datetime.strptime(seen[retailer], "%Y-%m-%d").date() if retailer in seen else None
            except (ValueError, TypeError):
                results.append(CheckResult(
                    name, CheckResult.WARNING,
                    f"Unparseable snapshot_date for {retailer}: {seen[retailer]!r}"))
                continue
            r_days = (today - r_last).days if r_last else None
            if r_days is not None and r_days <= threshold_days:
                results.append(CheckResult(name, CheckResult.OK, f"{retailer} current as of {r_last}"))
                continue
            what = (f"{retailer} last seen {r_last} ({r_days} day(s) ago)" if r_last
                    else f"No snapshot data for {retailer} at all")
            if cooldown_explains(retailer):
                results.append(CheckResult(name, CheckResult.WARNING,
                                           f"{what} - scraper cooldown active, expected"))
            else:
                results.append(CheckResult(name, CheckResult.ERROR,
                                           f"{what} - the scraper is failing or not running"))
```

Update the `--threshold-days` help text to say `(default: 0 = today must have data)`.

- [ ] **Step 9: Run the tests**

Run: `python -m pytest unit_testing/test_retry.py unit_testing/test_check_staleness.py unit_testing/test_pipeline_state.py unit_testing/test_migrate.py unit_testing/test_run_daily_resilience.py unit_testing/test_scrape_outcomes.py unit_testing/test_shell_scripts.py -q`

Expected: all PASS.

- [ ] **Step 10: Syntax-check the scripts and build-test the image**

Run: `sh -n deploy/entrypoint-single.sh && sh -n deploy/entrypoint.sh && docker build -t trackaroo:retry-test .`

Expected: no output from `sh -n`, and the build succeeds. Do **not** `docker run` it: that would start a live scrape.

- [ ] **Step 11: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add migrate.py db/schema.sql pipeline_state.py config.py run_daily.py check_staleness.py deploy/entrypoint-single.sh deploy/entrypoint.sh unit_testing/test_retry.py unit_testing/test_check_staleness.py unit_testing/test_migrate.py
git commit -m "feat(pipeline): hourly per-retailer retry until RETRY_UNTIL_HOUR; staleness alerts same day (#8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Partial results survive a timeout; the site shows each retailer's scrape time and matched count (R2, R3)

**Files:**
- Modify: `scraper/run_report.py` (add `RunReport`, `read_run_report`, `exit_code_for`)
- Modify: `scraper/snapshot_io.py` (add `save_category_snapshot`)
- Modify: `scraper/scorptec.py` (`scrape_scorptec` gains `only_category`; `main` saves per category)
- Modify: `scraper/umart.py` (`scrape_umart` gains `only_category`; `main`)
- Modify: `scraper/pccg.py` (`main` saves per category)
- Modify: `run_daily.py` (`run_scraper` passes `TRACKAROO_RUN_REPORT` and reads it back)
- Modify: `web/src/lib/server/repos.ts`, `web/src/lib/health.ts`, `web/src/lib/components/HealthStrip.svelte`
- Create: `unit_testing/test_run_report.py`
- Test: `web/test/repos.test.ts`, `web/test/health.test.ts`, `web/test/components.test.ts`

**Interfaces:**
- Consumes: `EXIT_*` (Task 2); `record_outcomes` and `scrape_runs` (Task 4), which already store `ScrapeOutcome.matched`; `tableExists` (Task 3).
- Produces, in `scraper.run_report`:
  - `REPORT_ENV = "TRACKAROO_RUN_REPORT"`
  - `COUNTERS = ("matched", "pages_attempted", "pages_fetched", "cards_seen", "cards_dropped")`
  - `class RunReport(retailer: str, path: Optional[Path] = None)` with `.category(name) -> Dict[str, int]`, `.set(category, **counts)`, `.note(text)`, `.matched -> int`, `.to_dict()` and `.flush()`
  - `read_run_report(path) -> Optional[dict]`
  - `exit_code_for(report, categories=("cpu", "gpu")) -> int`
- Produces, in `scraper.snapshot_io`: `save_category_snapshot(data_dir: Path, retailer: str, category: str, scrape_date: str, watchlist, products, matched_ids) -> Path`.
- Produces: `scrape_scorptec(watchlist, only_category=None)` and `scrape_umart(watchlist, only_category=None)`. Both keep the same 3-tuple return.
- Produces, in web: `RetailerFreshness` gains the optional `lastRunAt`, `lastRunStatus` and `lastRunMatched`. `RetailerHealth` gains the optional `detail`. `FreshnessState` gains `'incomplete'`.

- [ ] **Step 1: Write the failing Python tests**

Create `unit_testing/test_run_report.py`:

```python
"""A scraper killed by the timeout keeps what it had finished (R2), and each
run's matched count reaches run_daily (R3)."""
import json
import subprocess
from pathlib import Path

import pytest

import run_daily
from scraper import scorptec, umart
from scraper.run_report import (
    EXIT_DEGRADED, EXIT_OK, REPORT_ENV, RunReport, exit_code_for, read_run_report,
)
from scraper.snapshot_io import save_category_snapshot

WATCHLIST = [
    {"model": "Ryzen 7 9800X3D", "category": "cpu", "brand": "AMD", "gen_tier": "current",
     "vram_gb": None, "search_terms": ["ryzen 7 9800x3d"]},
    {"model": "GeForce RTX 5070", "category": "gpu", "brand": "NVIDIA", "gen_tier": "current",
     "vram_gb": 12, "search_terms": ["rtx 5070"]},
]

CPU_CARD = {"name": "amd ryzen 7 9800x3d desktop processor", "full_description": "AMD Ryzen 7 9800X3D",
            "price_aud": 699.0, "stock_status": "in_stock",
            "url": "https://www.scorptec.com.au/product/cpu/amd-socket-am5/112233", "retailer_sku": "112233"}


class TestRunReport:
    def test_flush_writes_the_counts(self, tmp_path):
        path = tmp_path / "r.json"
        report = RunReport("umart", path=path)
        report.set("cpu", matched=27)
        report.note("hello")
        report.flush()

        data = read_run_report(path)
        assert data["retailer"] == "umart"
        assert data["matched"] == 27
        assert data["categories"]["cpu"]["matched"] == 27
        assert data["notes"] == ["hello"]

    def test_without_a_path_flush_is_a_no_op(self, monkeypatch):
        monkeypatch.delenv(REPORT_ENV, raising=False)
        RunReport("umart").flush()  # must not raise or write anywhere

    def test_the_path_comes_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv(REPORT_ENV, str(tmp_path / "env.json"))
        assert RunReport("pccg").path == tmp_path / "env.json"

    def test_an_unreadable_report_reads_as_none(self, tmp_path):
        (tmp_path / "bad.json").write_text("{", encoding="utf-8")
        assert read_run_report(tmp_path / "bad.json") is None
        assert read_run_report(tmp_path / "absent.json") is None

    def test_exit_code_needs_both_categories(self):
        report = RunReport("x", path=None)
        report.set("cpu", matched=3)
        assert exit_code_for(report) == EXIT_DEGRADED
        report.set("gpu", matched=1)
        assert exit_code_for(report) == EXIT_OK


class TestPartialResultsSurvive:
    def test_scorptec_killed_during_gpus_keeps_the_cpus(self, tmp_path, monkeypatch):
        def pages(url, category_path="", **kwargs):
            if "/cpu/" in url:
                return [CPU_CARD] if url.endswith("amd-am5-9000") else []
            raise RuntimeError("killed by run_daily's timeout")

        monkeypatch.setattr(scorptec, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(scorptec, "DATA_DIR", tmp_path)
        monkeypatch.setattr(scorptec, "scrape_all_pages", pages)
        monkeypatch.setenv(REPORT_ENV, str(tmp_path / "report.json"))

        with pytest.raises(RuntimeError):
            scorptec.main()

        [cpu_file] = tmp_path.glob("cpu_scorptec_*.json")
        assert json.loads(cpu_file.read_text(encoding="utf-8"))["matched"] == 1
        assert not list(tmp_path.glob("gpu_scorptec_*.json"))
        assert read_run_report(tmp_path / "report.json")["categories"]["cpu"]["matched"] == 1

    def test_umart_saves_each_category_as_it_finishes(self, tmp_path, monkeypatch):
        calls = []

        def fake_scrape(wl, only_category=None, **kwargs):
            calls.append(only_category)
            if only_category == "gpu":
                raise RuntimeError("killed")
            return [], set(), {}

        monkeypatch.setattr(umart, "load_watchlist", lambda: WATCHLIST)
        monkeypatch.setattr(umart, "DATA_DIR", tmp_path)
        monkeypatch.setattr(umart, "scrape_umart", fake_scrape)

        with pytest.raises(RuntimeError):
            umart.main()
        assert calls == ["cpu", "gpu"]
        assert list(tmp_path.glob("cpu_umart_*.json"))

    def test_incremental_save_never_downgrades(self, tmp_path):
        """Review Focus 4: a partial re-run parks its result instead of overwriting."""
        rich = [dict(CPU_CARD, url=f"https://x/{i}", watchlist_model="Ryzen 7 9800X3D",
                     watchlist_category="cpu") for i in range(5)]
        save_category_snapshot(tmp_path, "scorptec", "cpu", "29_September_2026", WATCHLIST, rich, {0})
        written = save_category_snapshot(tmp_path, "scorptec", "cpu", "29_September_2026",
                                         WATCHLIST, rich[:1], {0})

        assert ".partial-" in written.name
        main_file = tmp_path / "cpu_scorptec_29_September_2026.json"
        assert json.loads(main_file.read_text(encoding="utf-8"))["matched"] == 5


class TestRunScraperReadsTheReport:
    def test_a_timeout_still_reports_what_was_matched(self, monkeypatch):
        seen = {}

        def fake_run(cmd, capture_output, text, timeout, env):
            seen["path"] = Path(env[REPORT_ENV])
            seen["path"].write_text(json.dumps({
                "retailer": "scorptec", "matched": 41,
                "categories": {"cpu": {"matched": 41}}, "notes": [],
            }), encoding="utf-8")
            raise subprocess.TimeoutExpired(cmd, timeout)

        monkeypatch.setattr(run_daily.subprocess, "run", fake_run)

        outcome = run_daily.run_scraper("Scorptec", "scraper.scorptec", "scorptec")

        assert outcome.status == "timeout"
        assert outcome.matched == 41
        assert outcome.report["categories"]["cpu"]["matched"] == 41
        assert not seen["path"].exists()  # temp report cleaned up

    def test_the_scraper_notes_become_the_outcome_detail(self, monkeypatch):
        def fake_run(cmd, capture_output, text, timeout, env):
            Path(env[REPORT_ENV]).write_text(json.dumps({
                "retailer": "pccg", "matched": 0, "categories": {},
                "notes": ["circuit breaker tripped for cpu"],
            }), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 2)

        monkeypatch.setattr(run_daily.subprocess, "run", fake_run)

        outcome = run_daily.run_scraper("PCCG", "scraper.pccg", "pccg")

        assert outcome.status == "degraded"
        assert outcome.detail == "circuit breaker tripped for cpu"

    def test_the_matched_count_reaches_scrape_runs(self, isolated_pipeline, monkeypatch):
        import sqlite3
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "ok", 0, matched=123))

        run_daily.run(run_daily.build_parser().parse_args(["--umart"]))

        conn = sqlite3.connect(str(isolated_pipeline.db_path))
        assert conn.execute("SELECT matched FROM scrape_runs WHERE retailer = 'umart'").fetchone()[0] == 123
        conn.close()
```

`amd-am5-9000` is the key whose URL ends that way in `scorptec.CATEGORY_URLS`, so exactly one card is matched.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_run_report.py -q`

Expected: FAIL with `ImportError: cannot import name 'RunReport'`.

- [ ] **Step 3: `RunReport`**

Append to `scraper/run_report.py`, adding `import json`, `import logging`, `import os`, `from datetime import datetime`, `from pathlib import Path` and `from typing import Any, Dict, List, Optional, Sequence` under `from __future__`:

```python
LOGGER = logging.getLogger(__name__)

# run_daily passes a temp path here; the scraper writes its counts to it after
# every category, so they survive run_daily's timeout kill (R2, R3). Unset
# (a scraper run by hand) makes every flush a no-op.
REPORT_ENV = "TRACKAROO_RUN_REPORT"

# Per-category counters. matched is set in Task 5; the page and card counters
# are filled by the scrapers' telemetry (Task 7, #14).
COUNTERS = ("matched", "pages_attempted", "pages_fetched", "cards_seen", "cards_dropped")


class RunReport:
    """Per-run telemetry a scraper hands back to run_daily."""

    def __init__(self, retailer: str, path: Optional[Path] = None) -> None:
        self.retailer = retailer
        env = os.environ.get(REPORT_ENV)
        self.path = path if path is not None else (Path(env) if env else None)
        self.categories: Dict[str, Dict[str, int]] = {}
        self.notes: List[str] = []

    def category(self, name: str) -> Dict[str, int]:
        """The live counter dict for one category (created on first use)."""
        return self.categories.setdefault(name, {c: 0 for c in COUNTERS})

    def set(self, category: str, **counts: int) -> None:
        self.category(category).update(counts)

    def note(self, text: str) -> None:
        self.notes.append(text)

    @property
    def matched(self) -> int:
        return sum(c["matched"] for c in self.categories.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "retailer": self.retailer,
            "matched": self.matched,
            "categories": self.categories,
            "notes": self.notes,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def flush(self) -> None:
        """Write the report now (atomically). Never raises."""
        if self.path is None:
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self.to_dict()), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            LOGGER.warning("Could not write run report %s: %s", self.path, e)


def read_run_report(path: Path) -> Optional[Dict[str, Any]]:
    """The report a scraper left at ``path``, or None if it never wrote one."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def exit_code_for(report: RunReport, categories: Sequence[str] = ("cpu", "gpu")) -> int:
    """EXIT_OK when every category matched something, else EXIT_DEGRADED (#7)."""
    return EXIT_OK if all(report.category(c)["matched"] > 0 for c in categories) else EXIT_DEGRADED
```

- [ ] **Step 4: `save_category_snapshot`**

Append to `scraper/snapshot_io.py`:

```python
def save_category_snapshot(
    data_dir: Path,
    retailer: str,
    category: str,
    scrape_date: str,
    watchlist: List[Dict[str, Any]],
    products: List[Dict[str, Any]],
    matched_ids: Any,
) -> Path:
    """Build and save one category's snapshot, the moment it is done (R2).

    ``matched_ids`` are indices into ``watchlist``. Goes through save_snapshot,
    so a partial result never replaces a fuller file already on disk.
    """
    unmatched = [
        wp["model"] for i, wp in enumerate(watchlist)
        if wp["category"] == category and i not in matched_ids
    ]
    data = build_snapshot(
        retailer=retailer,
        scrape_date=scrape_date,
        category=category,
        total_watchlist=len(watchlist),
        products=products,
        unmatched_models=unmatched,
    )
    return save_snapshot(data_dir / f"{category}_{retailer}_{scrape_date}.json", data)
```

- [ ] **Step 5: Scrapers save per category**

`scraper/scorptec.py`:
- Change the imports to `from scraper.run_report import RunReport, exit_code_for` and `from scraper.snapshot_io import save_category_snapshot`.
- Change the signature to `def scrape_scorptec(watchlist: List[WatchlistProduct], only_category: Optional[str] = None) -> Tuple[...]` (same return type).
- Make the first lines of its `for cat_key, cat_url in CATEGORY_URLS.items():` loop:

```python
        if only_category and not cat_key.startswith(f"{only_category}_"):
            continue
```

- Add `Args: only_category: "cpu" or "gpu" to scrape one category; None for both.` to the docstring.
- Replace `main()` with:

```python
def main() -> int:
    setup_logging()
    logger.info("Loading watchlist...")
    watchlist = load_watchlist()
    logger.info("  %d products in watchlist", len(watchlist))

    report = RunReport("scorptec")
    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    results: List[Dict[str, Any]] = []
    matched_ids: Set[int] = set()
    all_scraped: Dict[str, List[Dict[str, Any]]] = {}
    for category in ("cpu", "gpu"):
        logger.info("\nScraping Scorptec %s...", category.upper())
        cat_results, cat_ids, cat_scraped = scrape_scorptec(watchlist, only_category=category)
        # Saved the moment the category is done. run_daily kills a scraper at
        # SCRAPER_TIMEOUT_SECONDS, and results used to be saved only at the very
        # end, so a slow GPU pass cost the finished CPUs as well (R2).
        save_category_snapshot(DATA_DIR, "scorptec", category, today, watchlist, cat_results, cat_ids)
        report.set(category, matched=len(cat_results))
        report.flush()
        results.extend(cat_results)
        matched_ids |= cat_ids
        all_scraped.update(cat_scraped)

    logger.info("\n%s\nResults: %d matched / %d total", "=" * 60, len(results), len(watchlist))
    analyze_unmatched(watchlist, matched_ids, all_scraped)

    code = exit_code_for(report)
    if code != EXIT_OK:
        logger.error("Scorptec scrape incomplete: %s", {c: v["matched"] for c, v in report.categories.items()})
    return code
```

(Keep `EXIT_OK` in the imports. Remove the now-unused `build_snapshot`, `save_snapshot` and `EXIT_DEGRADED` imports if nothing else uses them.)

`scraper/umart.py`:
- Imports: the same `RunReport, exit_code_for` and `save_category_snapshot`.
- Change the signature to `def scrape_umart(watchlist, only_category: Optional[str] = None)`.
- Make the first line of its category loop `if only_category and category != only_category: continue`.
- Replace `main()` with:

```python
def main() -> int:
    setup_logging()
    logger.info("Loading watchlist...")
    watchlist = load_watchlist()
    logger.info("  %d products in watchlist", len(watchlist))

    report = RunReport("umart")
    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    for category in ("cpu", "gpu"):
        logger.info("\nScraping Umart %s...", category.upper())
        products, matched_ids, _ = scrape_umart(watchlist, only_category=category)
        # Saved per category so a timeout during GPUs keeps the CPUs (R2).
        save_category_snapshot(DATA_DIR, "umart", category, today, watchlist, products, matched_ids)
        report.set(category, matched=len(products))
        report.flush()

    logger.info("\n%s\nResults: %d matched / %d total", "=" * 60, report.matched, len(watchlist))
    code = exit_code_for(report)
    if code != EXIT_OK:
        logger.error("Umart scrape incomplete: %s", {c: v["matched"] for c, v in report.categories.items()})
    return code
```

`scraper/pccg.py`:
- Imports: add `RunReport, exit_code_for` to the run_report import, and replace the snapshot_io import with `from scraper.snapshot_io import save_category_snapshot`.
- Replace `main()` from the cooldown check onward with:

```python
    report = RunReport("pccg")

    # Respect a circuit-breaker cooldown before doing anything else.
    if _cooldown_active():
        LOGGER.warning(
            "Skipping PCCG scrape: cooldown still active (file %s, window %.0fh). "
            "This is expected handled behaviour, not an error.",
            PCCG_COOLDOWN_FILE, PCCG_COOLDOWN_HOURS,
        )
        report.note(f"skipped: circuit-breaker cooldown active ({PCCG_COOLDOWN_HOURS:.0f}h window)")
        report.flush()
        return EXIT_SKIPPED

    today = date.today().strftime(FILE_DATE_FORMAT)
    DATA_DIR.mkdir(exist_ok=True)

    all_results: list[Dict[str, Any]] = []
    all_matched: set[int] = set()
    all_tripped: list[str] = []

    for i, category in enumerate(["cpu", "gpu"]):
        results, matched, tripped = scrape_category(category, watchlist)
        # Saved per category so a timeout during GPUs keeps the CPUs (R2).
        save_category_snapshot(DATA_DIR, "pccg", category, today, watchlist, results, matched)
        report.set(category, matched=len(results))
        report.flush()
        all_results.extend(results)
        all_matched.update(matched)
        LOGGER.info("  %s: %d matched", category.upper(), len(results))
        if tripped:
            all_tripped.append(category)
            report.note(f"circuit breaker tripped for {category} (empty catalogue - treated as a block)")
            report.flush()
        # Short pause between category passes -- same Algolia index and IP.
        if i == 0:
            LOGGER.info("  Pausing %.1fs before next category pass...", CATEGORY_PASS_DELAY)
            time.sleep(CATEGORY_PASS_DELAY)

    if not all_tripped:
        _clear_cooldown()
    else:
        LOGGER.error("PCCG scrape incomplete - circuit breaker tripped for: %s", ", ".join(all_tripped))

    unmatched = [wp["model"] for i, wp in enumerate(watchlist) if i not in all_matched]
    LOGGER.info("\n%s\nTotal: %d matched / %d", "=" * 60, len(all_results), len(watchlist))
    LOGGER.info("Unmatched: %d", len(unmatched))
    for m in unmatched:
        LOGGER.info("  - %s", m)

    if all_tripped:
        return EXIT_DEGRADED
    return exit_code_for(report)
```

Update the Task 2 test fakes in `unit_testing/test_scrape_outcomes.py`, which now receive `only_category`:
- In `test_scorptec_with_an_empty_gpu_category_is_degraded`, use `lambda wl, only_category=None, **k: ([_match("scorptec", "Ryzen 7 9800X3D", "cpu")], {0}, {}) if only_category == "cpu" else ([], set(), {})`.
- In `test_scorptec_with_both_categories_is_ok`, use `lambda wl, only_category=None, **k: ([_match("scorptec", "Ryzen 7 9800X3D", "cpu")], {0}, {}) if only_category == "cpu" else ([_match("scorptec", "GeForce RTX 5070", "gpu")], {1}, {})`.

- [ ] **Step 6: `run_scraper` passes and reads the report**

In `run_daily.py`:
- Add `import os`, `import tempfile` and `from pathlib import Path`.
- Change the run_report import to `from scraper.run_report import EXIT_AUTH, EXIT_DEGRADED, EXIT_OK, EXIT_SKIPPED, REPORT_ENV, read_run_report`.
- Replace `run_scraper` with:

```python
def run_scraper(name: str, module: str, label: str) -> ScrapeOutcome:
    """Run a scraper module as a subprocess and classify what happened.

    The scraper writes per-category counts to a temp run report as it goes
    (scraper/run_report.py). The report survives the timeout kill below; the
    exit code does not (R2, R3).
    """
    LOGGER.info("\n%s\nScraping %s...\n%s", "=" * 60, name, "=" * 60)
    started = _now()
    start = time.time()
    fd, report_name = tempfile.mkstemp(prefix=f"trackaroo-{label}-", suffix=".json")
    os.close(fd)
    report_path = Path(report_name)
    report_path.unlink()  # absence means "the scraper never reported"

    status, exit_code = "failed", None
    try:
        result = subprocess.run(
            [sys.executable, "-m", module],
            capture_output=False,
            text=True,
            timeout=SCRAPER_TIMEOUT_SECONDS,
            env={**os.environ, REPORT_ENV: str(report_path)},
        )
        exit_code = result.returncode
        status = status_for_exit(exit_code)
    except subprocess.TimeoutExpired:
        status = "timeout"
    except Exception as e:  # noqa: BLE001 - CLI wrapper reports any failure
        LOGGER.error("\n%s error: %s", name, e)

    report = read_run_report(report_path)
    try:
        report_path.unlink()
    except OSError:
        pass

    outcome = ScrapeOutcome(
        label, status, exit_code, started_at=started, finished_at=_now(),
        matched=report.get("matched") if report else None,
        detail="; ".join(report.get("notes") or []) if report else "",
        report=report,
    )
    elapsed = time.time() - start
    if outcome.ok:
        LOGGER.info("\n%s completed in %.1fs (%s matched)", name, elapsed, outcome.matched)
    elif status == "timeout":
        LOGGER.error("\n%s timed out after %ds - kept %d matched product(s) saved before the kill",
                     name, SCRAPER_TIMEOUT_SECONDS, outcome.matched or 0)
    else:
        LOGGER.error("\n%s %s (exit code %s) after %.1fs", name, status, exit_code, elapsed)
    return outcome
```

- [ ] **Step 7: Run the Python tests**

Run: `python -m pytest unit_testing/test_run_report.py unit_testing/test_scrape_outcomes.py unit_testing/test_scraper.py unit_testing/test_umart.py unit_testing/test_pccg_query_budget.py unit_testing/test_pccg_reliability.py unit_testing/test_snapshot_io.py unit_testing/test_retry.py -q`

Expected: all PASS.

- [ ] **Step 8: Write the failing web tests**

Append to `web/test/repos.test.ts`:

```ts
describe('getRetailerFreshness carries the last scrape run (R3)', () => {
	it('reports the latest run time, status and matched count per retailer', () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-runs-'));
		const d = openDatabase(path.join(dir, 'r.db'), { readonly: false, fileMustExist: false });
		try {
			d.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
			d.exec(`INSERT INTO active_retailers (retailer, position) VALUES ('scorptec', 0), ('umart', 1);
				INSERT INTO scrape_runs (retailer, run_date, started_at, finished_at, status, matched)
				VALUES ('scorptec', '2026-09-29', '2026-09-29T04:00:02', '2026-09-29T04:03:10', 'failed', NULL),
				       ('scorptec', '2026-09-29', '2026-09-29T05:00:01', '2026-09-29T05:02:44', 'ok', 312);`);
			expect(getRetailerFreshness(d)).toEqual([
				{
					retailer: 'scorptec',
					latestSnapshotDate: null,
					lastRunAt: '2026-09-29T05:02:44',
					lastRunStatus: 'ok',
					lastRunMatched: 312
				},
				{
					retailer: 'umart',
					latestSnapshotDate: null,
					lastRunAt: null,
					lastRunStatus: null,
					lastRunMatched: null
				}
			]);
		} finally {
			d.close();
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});

	it('works without a scrape_runs table (Review Focus 5)', () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-noruns-'));
		const d = openDatabase(path.join(dir, 'r.db'), { readonly: false, fileMustExist: false });
		try {
			d.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
			d.exec(
				"DROP TABLE scrape_runs; INSERT INTO active_retailers (retailer, position) VALUES ('umart', 0);"
			);
			expect(getRetailerFreshness(d)[0]).toMatchObject({ retailer: 'umart', lastRunAt: null });
		} finally {
			d.close();
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});
```

Append to the `retailerHealth` describe in `web/test/health.test.ts` (`NOW` is `2026-08-25T09:00:00`):

```ts
	it("shows today's run time and matched count (R3)", () => {
		const [row] = retailerHealth(
			[
				{
					retailer: 'umart',
					latestSnapshotDate: '2026-08-25',
					lastRunAt: '2026-08-25T04:12:33',
					lastRunStatus: 'ok',
					lastRunMatched: 182
				}
			],
			NOW
		);
		expect(row).toMatchObject({ state: 'fresh', text: 'today 04:12', detail: '182 matched' });
	});

	it('flags a run that failed today as incomplete, even with older data present', () => {
		const [row] = retailerHealth(
			[
				{
					retailer: 'pccg',
					latestSnapshotDate: '2026-08-24',
					lastRunAt: '2026-08-25T05:01:00',
					lastRunStatus: 'timeout',
					lastRunMatched: 21
				}
			],
			NOW
		);
		expect(row.state).toBe('incomplete');
		expect(row.text).toBe('timeout at 05:01');
	});

	it("ignores yesterday's run when judging today", () => {
		const [row] = retailerHealth(
			[
				{
					retailer: 'pccg',
					latestSnapshotDate: '2026-08-24',
					lastRunAt: '2026-08-24T04:00:00',
					lastRunStatus: 'failed',
					lastRunMatched: null
				}
			],
			NOW
		);
		expect(row.state).toBe('recent');
		expect(row.detail).toBeNull();
	});
```

Append to the `HealthStrip` describe in `web/test/components.test.ts`:

```ts
	it('shows the run detail next to the age when there is one', () => {
		const html = renderComponent(HealthStrip, {
			retailers: [
				{ retailer: 'umart', label: 'Umart', state: 'fresh', days: 0, text: 'today 04:12', detail: '182 matched' },
				{ retailer: 'pccg', label: 'PCCG', state: 'incomplete', days: 1, text: 'timeout at 05:01', detail: null }
			],
			latestSnapshotDate: '2026-08-25',
			snapshotDays: 17,
			snapshotCount: 4988
		});
		expect(html).toContain('today 04:12');
		expect(html).toContain('182 matched');
		expect(html).toContain('timeout at 05:01');
	});
```

- [ ] **Step 9: Run to verify they fail**

Run (from `web/`): `npm test -- repos health components`

Expected: FAIL. The `lastRun*` keys are missing, `detail` is undefined, and the state is not `'incomplete'`.

- [ ] **Step 10: Implement the web side**

In `repos.ts`, extend `RetailerFreshness` and `getRetailerFreshness`:

```ts
export interface RetailerFreshness {
	retailer: Retailer;
	latestSnapshotDate: string | null;
	// Latest scrape_runs row (R3): local wall-clock 'YYYY-MM-DDTHH:MM:SS', its
	// status, and the products it matched. Optional so callers building rows by
	// hand (tests, older data) need not supply them.
	lastRunAt?: string | null;
	lastRunStatus?: string | null;
	lastRunMatched?: number | null;
}
```

At the end of `getRetailerFreshness`, replace the `return [...active, ...inactive].map(...)` with:

```ts
	const runs = tableExists(db, 'scrape_runs')
		? (db
				.prepare(
					`SELECT r.retailer AS retailer, r.finished_at AS at, r.status AS status, r.matched AS matched
					 FROM scrape_runs r
					 WHERE r.id = (SELECT MAX(id) FROM scrape_runs WHERE retailer = r.retailer)`
				)
				.all() as Array<{ retailer: string; at: string; status: string; matched: number | null }>)
		: [];
	const runBy = new Map(runs.map((r) => [r.retailer, r]));

	return [...active, ...inactive].map((retailer) => {
		const run = runBy.get(retailer);
		return {
			retailer: retailer as Retailer,
			latestSnapshotDate: latestBy.get(retailer) ?? null,
			lastRunAt: run?.at ?? null,
			lastRunStatus: run?.status ?? null,
			lastRunMatched: run?.matched ?? null
		};
	});
```

(The Task 3 test's `toEqual` on `[retailer, latestSnapshotDate]` pairs is unaffected.)

Replace `web/src/lib/health.ts` from `export type FreshnessState` onward with:

```ts
export type FreshnessState = 'fresh' | 'recent' | 'stale' | 'never' | 'incomplete';

export interface RetailerHealth {
	retailer: string;
	label: string;
	state: FreshnessState;
	days: number | null;
	// Always states the age in words -- colour is never the only carrier.
	text: string;
	// "312 matched" from today's run, when there was one (R3).
	detail?: string | null;
}

// scrape_runs statuses meaning today's data is short (#7, R3). 'skipped' (a
// PCCG cooldown) is expected and not listed.
const INCOMPLETE_STATUSES = new Set(['degraded', 'failed', 'timeout', 'auth']);

// The spec names fresh / cooling-down / stale but leaves one-day-behind
// unnamed, which is the most common state of all: the pipeline runs at 04:00,
// so every retailer is one day behind until the morning run. "recent" keeps
// that honest without crying wolf. The >= 2 day stale boundary is the spec's.
export function classifyFreshness(days: number | null): FreshnessState {
	if (days === null) return 'never';
	if (days === 0) return 'fresh';
	if (days === 1) return 'recent';
	return 'stale';
}

function localIsoDate(now: Date): string {
	const mm = String(now.getMonth() + 1).padStart(2, '0');
	const dd = String(now.getDate()).padStart(2, '0');
	return `${now.getFullYear()}-${mm}-${dd}`;
}

export function retailerHealth(
	rows: RetailerFreshness[],
	now: Date = new Date()
): RetailerHealth[] {
	const today = localIsoDate(now);
	return rows.map((row) => {
		const days = row.latestSnapshotDate === null ? null : daysBehindToday(row.latestSnapshotDate, now);
		// The pipeline stores local wall-clock times, so the time is sliced, not
		// parsed: parsing would shift it by the viewer's timezone and could differ
		// between server and browser.
		const runToday = row.lastRunAt && row.lastRunAt.slice(0, 10) === today ? row.lastRunAt : null;
		const time = runToday ? runToday.slice(11, 16) : null;

		let state = classifyFreshness(days);
		if (runToday && row.lastRunStatus && INCOMPLETE_STATUSES.has(row.lastRunStatus)) {
			state = 'incomplete';
		}

		let text: string;
		if (state === 'incomplete') text = `${row.lastRunStatus} at ${time}`;
		else if (state === 'never') text = 'missing';
		else if (days === 0) text = time ? `today ${time}` : 'today';
		else text = stalenessLabel(days as number);

		return {
			retailer: row.retailer,
			// An unknown slug falls back to itself so a newly-added retailer
			// shows up rather than rendering blank.
			label: retailerLabel(row.retailer),
			state,
			days,
			text,
			detail: runToday && row.lastRunMatched != null ? `${row.lastRunMatched} matched` : null
		};
	});
}
```

In `HealthStrip.svelte`:
- Update the comment above `pillClass` to say that `stale`, `never` and `incomplete` all take the warning tone.
- In the pill, after `<span>{r.text}</span>`, add:

```svelte
						{#if r.detail}
							<span class="text-text-muted">· {r.detail}</span>
						{/if}
```

(`pillClass` and `marker` already fall through to the warning tone and `▲` for any state other than `fresh` and `recent`, which covers `incomplete`.)

- [ ] **Step 11: Run the web tests**

Run (from `web/`): `npm run check && npm test -- repos health components`

Expected: 0 errors, and all PASS.

- [ ] **Step 12: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add scraper/run_report.py scraper/snapshot_io.py scraper/scorptec.py scraper/umart.py scraper/pccg.py run_daily.py unit_testing/test_run_report.py unit_testing/test_scrape_outcomes.py web/src/lib/server/repos.ts web/src/lib/health.ts web/src/lib/components/HealthStrip.svelte web/test/repos.test.ts web/test/health.test.ts web/test/components.test.ts
git commit -m "fix(scrapers): save per category so a timeout keeps partial results; show scrape time and matched count (R2, R3)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: A rejected PCCG Algolia key is an alerting error, not an empty catalogue (#11a)

**Files:**
- Modify: `scraper/pccg.py` (`AlgoliaAuthError`; `algolia_fetch_catalogue` `:510-512`; `main`)
- Modify: `.env.example:5-9`
- Modify: `DEPLOYMENT.md` (add the "PCCG key rotation" runbook)
- Test: `unit_testing/test_pccg_reliability.py`, `unit_testing/test_scrape_outcomes.py`

**Interfaces:**
- Consumes: `EXIT_AUTH` (Task 2); `RunReport` and per-category `main` (Task 5); `status_for_exit` and `outcome_alert_line` (Tasks 1–2).
- Produces, in `scraper.pccg`: `class AlgoliaAuthError(RuntimeError)` with `.status: int`. `algolia_fetch_catalogue` raises it on 401/403. `main()` returns `EXIT_AUTH`, writes no cooldown file and no snapshot for the category it could not fetch, and leaves a report note that names `ALGOLIA_API_KEY`.

- [ ] **Step 1: Write the failing tests**

Append to `unit_testing/test_pccg_reliability.py`. Add `from scraper import pccg` and `from scraper.pccg import AlgoliaAuthError, algolia_fetch_catalogue` to the imports, plus `from scraper.run_report import EXIT_AUTH`:

```python
def _status(code):
    def _respond(*args, **kwargs):
        resp = unittest.mock.Mock()
        resp.status_code = code
        resp.text = "Invalid Application-ID or API key"
        resp.headers = {}
        return resp
    return _respond


@pytest.mark.parametrize("code", [401, 403])
def test_a_rejected_key_raises_instead_of_returning_an_empty_catalogue(monkeypatch, code):
    """#11a: an empty catalogue trips the breaker and writes a 4h cooldown -- a
    rejected key must not look like that."""
    monkeypatch.setattr("scraper.pccg.requests.post", _status(code))
    with pytest.raises(AlgoliaAuthError) as exc:
        algolia_fetch_catalogue("CPUs")
    assert exc.value.status == code


def test_a_rejected_key_exits_4_with_no_cooldown_and_no_empty_snapshot(tmp_path, monkeypatch):
    cooldown = tmp_path / "pccg_cooldown.json"
    monkeypatch.setattr("scraper.pccg.PCCG_COOLDOWN_FILE", cooldown)
    monkeypatch.setattr("scraper.pccg.DATA_DIR", tmp_path)
    monkeypatch.setattr("scraper.pccg.requests.post", _status(403))
    monkeypatch.setenv("TRACKAROO_RUN_REPORT", str(tmp_path / "report.json"))

    assert pccg.main() == EXIT_AUTH
    assert not cooldown.exists()
    assert not list(tmp_path.glob("*_pccg_*.json"))
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert "ALGOLIA_API_KEY" in report["notes"][0]
```

Append to `unit_testing/test_scrape_outcomes.py`:

```python
def test_an_auth_outcome_alerts_with_the_fix(isolated_pipeline, monkeypatch):
    monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
        label, "auth" if label == "pccg" else "ok", 4 if label == "pccg" else 0,
        detail="Algolia rejected the PCCG search key (HTTP 403) - update ALGOLIA_API_KEY" if label == "pccg" else ""))

    run_daily.run(_args())

    [line] = [l for l in isolated_pipeline.alerts[0] if "PCCG" in l]
    assert "credentials rejected" in line
    assert "ALGOLIA_API_KEY" in line
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_pccg_reliability.py unit_testing/test_scrape_outcomes.py -q`

Expected: FAIL with `ImportError: cannot import name 'AlgoliaAuthError'`.

- [ ] **Step 3: Raise on 401/403**

In `scraper/pccg.py`, after `_log_api_status_error`, add:

```python
class AlgoliaAuthError(RuntimeError):
    """PCCG's public search key was rejected (HTTP 401/403).

    Distinct from an empty catalogue (a block): backing off cannot fix a
    rotated key, so no cooldown is written and a human is paged (#11a).
    """

    def __init__(self, status: int) -> None:
        super().__init__(f"Algolia rejected the PCCG search key (HTTP {status})")
        self.status = status
```

In `algolia_fetch_catalogue`, replace

```python
                if r.status_code != 200:
                    _log_api_status_error(r)
                    return all_products
```

with

```python
                if r.status_code in (401, 403):
                    _log_api_status_error(r)
                    raise AlgoliaAuthError(r.status_code)
                if r.status_code != 200:
                    _log_api_status_error(r)
                    return all_products
```

Add `Raises: AlgoliaAuthError: the key was rejected (401/403).` to its docstring. `AlgoliaAuthError` is not a `requests.RequestException`, so the surrounding `except` lets it propagate. `scrape_category` does not catch it either.

In `main()`, wrap the category loop (from `for i, category in enumerate(["cpu", "gpu"]):` through the pause) in:

```python
    try:
        for i, category in enumerate(["cpu", "gpu"]):
            ...  # the Task 5 loop body, unchanged, indented one level
    except AlgoliaAuthError as e:
        LOGGER.error(
            "%s. No cooldown written: waiting cannot fix a rejected key. Update "
            "ALGOLIA_API_KEY - see DEPLOYMENT.md, 'PCCG key rotation'.", e,
        )
        report.note(f"{e} - update ALGOLIA_API_KEY (DEPLOYMENT.md: 'PCCG key rotation')")
        report.flush()
        return EXIT_AUTH
```

Add `EXIT_AUTH` to the run_report import. The CPU pass raises before `save_category_snapshot`, so no empty file is written.

- [ ] **Step 4: Comment the key out of `.env.example`**

Replace `.env.example:5-9` with:

```sh
# ── Algolia credentials (PCCG scraper) ────────────────────────────────
# The current public read-only search key is the default in scraper/pccg.py.
# Leave these COMMENTED OUT: an uncommented copy pins an old key in .env and
# silently overrides the code default after PCC rotates it (#11). Set them
# only when following DEPLOYMENT.md -> "PCCG key rotation".
# ALGOLIA_APP_ID=HPD3DBJ2IO
# ALGOLIA_API_KEY=9559cf1a6c7521a30ba0832ec6c38499
```

- [ ] **Step 5: Runbook**

In `DEPLOYMENT.md`, after "### PCCG scheduled retry", add:

```markdown
### PCCG key rotation

Symptom: a Discord alert "Scraper **PCCG** was refused by the retailer
(credentials rejected) ... update ALGOLIA_API_KEY", and `logs/trackaroo-*.log`
shows `Algolia auth rejected (403)`. PCC has rotated the public search key the
site embeds. The scraper writes **no** cooldown for this: waiting cannot fix it.

1. Open <https://www.pccasegear.com> in a browser, open DevTools -> Network,
   filter on `algolia`, and search the site for anything.
2. Click a `queries` request. Its request headers carry
   `x-algolia-application-id` and `x-algolia-api-key`.
3. Put both in `.env`: `ALGOLIA_APP_ID=...` and `ALGOLIA_API_KEY=...`.
4. Restart the container (`docker restart trackaroo`), or wait: the next
   hourly retry before `RETRY_UNTIL_HOUR` picks the new key up.
5. Update the defaults in `scraper/pccg.py` in a PR, then comment the two
   lines in `.env` out again, so a later rotation is not pinned by `.env`.

Not yet verified: whether the key is in the page HTML or only in a JS bundle.
The Network-tab method works either way.
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest unit_testing/test_pccg_reliability.py unit_testing/test_pccg_query_budget.py unit_testing/test_scrape_outcomes.py -q`

Expected: all PASS. The budget test still counts exactly 2 queries.

- [ ] **Step 7: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add scraper/pccg.py .env.example DEPLOYMENT.md unit_testing/test_pccg_reliability.py unit_testing/test_scrape_outcomes.py
git commit -m "fix(pccg): a rejected Algolia key alerts with the fix instead of cooling down silently (#11a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Scraper telemetry, real-HTML fixtures, selector-drift and match-drop rules (#14, #7b)

**Files:**
- Create: `unit_testing/fixtures/capture_fixtures.py`
- Create (by running the capture once): `unit_testing/fixtures/scorptec_gpu_nvidia_page1.html`, `unit_testing/fixtures/umart_cpu_page1.html`, `unit_testing/fixtures/pccg_cpus_catalogue.json`
- Create: `unit_testing/test_scraper_fixtures.py`
- Modify: `scraper/scorptec.py` (`fetch_page` backoff; `scrape_all_pages`, `parse_product_grid` and `scrape_scorptec` get stats)
- Modify: `scraper/umart.py` (`get_max_page` cap WARNING; `parse_product_grid`, `scrape_all_pages` and `scrape_umart` get stats)
- Modify: `scraper/pccg.py` (`algolia_fetch_catalogue` and `scrape_category` get stats)
- Modify: `health_checks.py` (add `check_run_report`, `check_match_count_drop`)
- Modify: `config.py` (`MATCH_DROP_RATIO`, `MATCH_DROP_WINDOW_DAYS`, `MATCH_DROP_MIN_HISTORY`)
- Modify: `run_daily.py` (report results into `failed`; the drop check in `_db_checks`)
- Test: `unit_testing/test_health_checks.py`, `unit_testing/test_scraper.py`

**Interfaces:**
- Consumes: `RunReport.category()` and `COUNTERS` (Task 5); `ScrapeOutcome.report` (Task 5); `_db_checks` (Task 1).
- Produces:
  - `scorptec.parse_product_grid(html, category_path="", stats=None)`
  - `scorptec.scrape_all_pages(url, category_path, max_pages=SCORPTEC_MAX_PAGES, stats=None)`
  - `scorptec.scrape_scorptec(watchlist, only_category=None, report=None)`
  - `umart.parse_product_grid(html, stats=None)`
  - `umart.scrape_all_pages(category_url, stats=None)`
  - `umart.scrape_umart(watchlist, only_category=None, report=None)`
  - `pccg.algolia_fetch_catalogue(category_filter, hits_per_page=..., max_pages=..., stats=None)`
  - `pccg.scrape_category(category, watchlist, report=None)`
  - `stats` is a `Dict[str, int]` whose counters are incremented: `pages_attempted`, `pages_fetched`, `cards_seen` and `cards_dropped`.
  - `health_checks.check_run_report(report: dict) -> list[CheckResult]`
  - `health_checks.check_match_count_drop(db_path=None, today: Optional[date] = None) -> list[CheckResult]`

- [ ] **Step 1: The capture script**

Create `unit_testing/fixtures/capture_fixtures.py`:

```python
"""One-off capture of real retailer pages for the scraper fixture tests (#14).

Run by hand, with the owner's OK, never from a test or CI. It makes three live
requests: one Scorptec NVIDIA grid page, Umart's CPU category page 1, and one
Algolia query for PCC's CPUs (hitsPerPage=20, which is 1 of the key's 100
queries/hour). Each page is cut to its first 8 product cards plus the
pagination links, with scripts and styles removed, so the fixtures stay small
and a retailer's markup change shows up as a readable diff.

    python unit_testing/fixtures/capture_fixtures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scraper import pccg, scorptec, umart  # noqa: E402

HERE = Path(__file__).resolve().parent
KEEP_CARDS = 8


def _trim(html: str, card_selector: str, pager_selector: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    kept = soup.select(card_selector)[:KEEP_CARDS] + soup.select(pager_selector)
    for tag in kept:
        for junk in tag.find_all(["script", "style"]):
            junk.decompose()
    body = "\n".join(str(t) for t in kept)
    return f"<html><body>\n{body}\n</body></html>\n"


def main() -> None:
    s_html = scorptec.fetch_page(scorptec.CATEGORY_URLS["gpu_nvidia"])
    u_html = umart.fetch_page(umart.CATEGORY_URLS["cpu"])
    if not s_html or not u_html:
        raise SystemExit("A fetch failed - nothing written.")
    (HERE / "scorptec_gpu_nvidia_page1.html").write_text(
        _trim(s_html, ".product-grid", "a.next[href]"), encoding="utf-8")
    (HERE / "umart_cpu_page1.html").write_text(
        _trim(u_html, ".goods-item", "a[href*='page=']"), encoding="utf-8")

    params = urlencode({
        "query": "", "hitsPerPage": 20, "page": 0,
        "attributesToRetrieve": pccg.STOCK_ATTRS,
        "filters": 'categories.lvl0:"CPUs"',
    })
    r = requests.post(pccg.ALGOLIA_URL, headers=pccg.HEADERS, timeout=15,
                      json={"requests": [{"indexName": pccg.ALGOLIA_INDEX, "params": params}]})
    r.raise_for_status()
    payload = r.json()
    # One page is the fixture: stop algolia_fetch_catalogue paginating over it.
    payload["results"][0]["nbPages"] = 1
    (HERE / "pccg_cpus_catalogue.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote 3 fixtures to {HERE}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Capture the fixtures (owner OK required)**

Ask the owner before running this: it makes 3 live requests. Then run `python unit_testing/fixtures/capture_fixtures.py`.

Expected: `Wrote 3 fixtures to ...`. Open each file and check that it holds 8 cards (20 hits for PCCG) and is under 40 KB.

- [ ] **Step 3: Write the failing tests**

Create `unit_testing/test_scraper_fixtures.py`:

```python
"""Each scraper's parser against real, trimmed retailer markup (#14).

When a retailer changes its HTML, re-run unit_testing/fixtures/capture_fixtures.py
(owner OK -- 3 live requests) and the diff of the fixture shows what moved.
"""
import json
import unittest.mock
from pathlib import Path

from health_checks import CheckResult, check_run_report
from scraper import pccg, scorptec, umart

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STOCK = {"in_stock", "out_of_stock", "preorder", "unknown"}


def _fixture(name):
    path = FIXTURES / name
    assert path.exists(), f"{name} missing - run python unit_testing/fixtures/capture_fixtures.py"
    return path.read_text(encoding="utf-8")


class TestScorptecFixture:
    HTML = "scorptec_gpu_nvidia_page1.html"

    def test_every_card_parses(self):
        stats = {}
        products = scorptec.parse_product_grid(_fixture(self.HTML), "graphics-cards/nvidia", stats=stats)

        assert (stats["cards_seen"], stats["cards_dropped"]) == (8, 0)
        assert len(products) == 8
        for p in products:
            assert p["price_aud"] > 0
            assert p["url"].startswith("https://www.scorptec.com.au/")
            assert p["retailer_sku"]
            assert p["stock_status"] in STOCK

    def test_the_page_links_to_the_next_one(self):
        assert scorptec.get_next_page_url(_fixture(self.HTML), scorptec.CATEGORY_URLS["gpu_nvidia"])

    def test_a_renamed_grid_class_is_reported_as_selector_drift(self):
        html = _fixture(self.HTML).replace("product-grid", "product-tile")
        stats = {"pages_attempted": 1, "pages_fetched": 1}

        assert scorptec.parse_product_grid(html, "graphics-cards/nvidia", stats=stats) == []
        results = check_run_report({"retailer": "scorptec", "categories": {"gpu": stats}})

        assert [r.status for r in results] == [CheckResult.ERROR]
        assert "selector drift at scorptec/gpu" in results[0].message


class TestUmartFixture:
    HTML = "umart_cpu_page1.html"

    def test_every_card_parses(self):
        stats = {}
        products = umart.parse_product_grid(_fixture(self.HTML), stats=stats)

        assert (stats["cards_seen"], stats["cards_dropped"]) == (8, 0)
        for p in products:
            assert p["price_aud"] > 0
            assert p["url"].startswith("https://www.umart.com.au/")
            assert p["retailer_sku"]
            assert p["stock_status"] in STOCK

    def test_the_page_count_comes_from_the_pager(self):
        assert umart.get_max_page(_fixture(self.HTML)) >= 2

    def test_a_503_on_page_2_of_3_is_a_pagination_hole(self, monkeypatch):
        html = _fixture(self.HTML)
        pages = {"x": html, "x?page=2": None, "x?page=3": html}
        monkeypatch.setattr("scraper.umart.get_max_page", lambda h: 3)
        monkeypatch.setattr("scraper.umart.fetch_page", lambda url, retries=None: pages[url])
        monkeypatch.setattr("scraper.umart.time.sleep", lambda s: None)
        stats = {}

        umart.scrape_all_pages("x", stats=stats)
        results = check_run_report({"retailer": "umart", "categories": {"cpu": stats}})

        assert (stats["pages_attempted"], stats["pages_fetched"]) == (3, 2)
        assert [(r.status, r.check_name) for r in results] == [(CheckResult.WARNING, "pagination_hole_umart_cpu")]


class TestPccgFixture:
    JSON = "pccg_cpus_catalogue.json"

    def test_every_hit_extracts(self):
        hits = json.loads(_fixture(self.JSON))["results"][0]["hits"]
        products = pccg._extract_products(hits)

        assert len(hits) == 20 and len(products) == 20
        for p in products:
            assert p["url"].startswith("https://www.pccasegear.com")
            assert pccg._parse_price(p["price"]) > 0
            assert p["stock_status"] in STOCK

    def test_the_catalogue_fetch_counts_its_page_and_cards(self, monkeypatch):
        payload = json.loads(_fixture(self.JSON))

        def post(*a, **k):
            resp = unittest.mock.Mock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = payload
            return resp

        monkeypatch.setattr("scraper.pccg.requests.post", post)
        stats = {}

        assert len(pccg.algolia_fetch_catalogue("CPUs", stats=stats)) == 20
        assert stats == {"pages_attempted": 1, "pages_fetched": 1, "cards_seen": 20, "cards_dropped": 0}
```

Append to `unit_testing/test_health_checks.py`, adding `check_match_count_drop, check_run_report` to its imports:

```python
class TestCheckRunReport:
    def test_a_clean_report_says_nothing(self):
        c = {"pages_attempted": 3, "pages_fetched": 3, "cards_seen": 60, "cards_dropped": 1}
        assert check_run_report({"retailer": "umart", "categories": {"gpu": c}}) == []

    def test_many_unparseable_cards_is_an_error(self):
        c = {"pages_attempted": 1, "pages_fetched": 1, "cards_seen": 20, "cards_dropped": 5}
        [r] = check_run_report({"retailer": "umart", "categories": {"gpu": c}})
        assert r.status == CheckResult.ERROR
        assert "5 of 20" in r.message


def _drop_db(db_path, series):
    """series: {date: listing count} for pccg/gpu."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('gpu', 'NVIDIA', 'RTX 5070', 1)")
    most = max(series.values())
    for i in range(1, most + 1):
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                     "VALUES (1, 'pccg', ?, 'active')", (f"https://x/{i}",))
    for day, n in series.items():
        for i in range(1, n + 1):
            conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                         "VALUES (?, ?, 100, 'in_stock')", (i, day))
    conn.commit()
    conn.close()


class TestMatchCountDrop:
    PRIOR = {f"2026-09-{d:02d}": 100 for d in range(22, 29)}

    def test_45_percent_of_the_median_is_an_error(self, db_path):
        """#7 acceptance: a PCCG day at 45% of its 7-day median produces an ERROR."""
        _drop_db(db_path, {**self.PRIOR, "2026-09-29": 45})
        [r] = check_match_count_drop(db_path, today=date(2026, 9, 29))
        assert (r.check_name, r.status) == ("match_drop_pccg_gpu", CheckResult.ERROR)
        assert "45 listings today" in r.message

    def test_90_percent_is_fine(self, db_path):
        _drop_db(db_path, {**self.PRIOR, "2026-09-29": 90})
        [r] = check_match_count_drop(db_path, today=date(2026, 9, 29))
        assert r.status == CheckResult.OK

    def test_too_little_history_is_not_judged(self, db_path):
        _drop_db(db_path, {"2026-09-27": 100, "2026-09-28": 100, "2026-09-29": 10})
        assert check_match_count_drop(db_path, today=date(2026, 9, 29)) == []

    def test_a_missing_day_is_left_to_today_coverage(self, db_path):
        _drop_db(db_path, self.PRIOR)
        assert check_match_count_drop(db_path, today=date(2026, 9, 29)) == []
```

Append to `TestFetchPage` in `unit_testing/test_scraper.py`:

```python
    def test_non_200_backs_off_before_retrying(self, monkeypatch):
        """#14: a 503 used to be retried immediately, a burst at a CDN that had just said no."""
        from scraper.scorptec import fetch_page
        import config
        responses = [self._resp(503), self._resp(200, "ok")]
        sleeps = []
        monkeypatch.setattr("scraper.scorptec.requests.get", lambda url, headers=None, timeout=None: responses.pop(0))
        monkeypatch.setattr("scraper.scorptec.time.sleep", sleeps.append)

        assert fetch_page("https://example.com") == "ok"
        assert sleeps == [config.SCORPTEC_RETRY_DELAY]
```

- [ ] **Step 4: Run to verify they fail**

Run: `python -m pytest unit_testing/test_scraper_fixtures.py unit_testing/test_health_checks.py unit_testing/test_scraper.py -q`

Expected: FAIL with `ImportError: cannot import name 'check_run_report'`, and `TypeError: ... unexpected keyword argument 'stats'`.

- [ ] **Step 5: Scorptec telemetry**

In `fetch_page`, replace the retry loop body with:

```python
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=SCORPTEC_TIMEOUT_SECONDS)
            if r.status_code == 200:
                return r.text
            logger.warning("Non-200 status %s for %s (attempt %d/%d)",
                           r.status_code, url, attempt + 1, retries + 1)
        except requests.RequestException as e:
            logger.warning("Attempt %d failed for %s: %s", attempt + 1, url, e)
        # Back off before every retry. A non-200 used to be retried at once:
        # a burst of requests at a CDN that had just refused one (#14).
        if attempt < retries:
            time.sleep(SCORPTEC_RETRY_DELAY)
    return None
```

In `scrape_all_pages`:
- Add `stats: Optional[Dict[str, int]] = None` as the last parameter.
- Make its first line `counts = stats if stats is not None else {}`.
- In the loop, replace the fetch-and-parse lines with:

```python
        counts["pages_attempted"] = counts.get("pages_attempted", 0) + 1
        html = fetch_page(current_url)
        if not html:
            logger.warning("Failed to fetch page %d, stopping pagination (%d product(s) kept from earlier pages).",
                           page, len(all_products))
            break
        counts["pages_fetched"] = counts.get("pages_fetched", 0) + 1

        products = parse_product_grid(html, category_path=category_path, stats=counts)
```

In `parse_product_grid`:
- Add `stats: Optional[Dict[str, int]] = None`.
- Replace `for grid in soup.select(".product-grid"):` with:

```python
    grids = soup.select(".product-grid")
    dropped = 0
    for grid in grids:
```

- Replace the final `if name and price is not None: products.append({...})` with the same append, followed by:

```python
        else:
            dropped += 1
            logger.debug("Dropped card sku=%r: name=%r price=%r", sku, name, price_str)
```

- Before `return products`, add:

```python
    if stats is not None:
        stats["cards_seen"] = stats.get("cards_seen", 0) + len(grids)
        stats["cards_dropped"] = stats.get("cards_dropped", 0) + dropped
    if dropped:
        logger.warning("Dropped %d of %d product card(s): no name or unparseable price", dropped, len(grids))
```

In `scrape_scorptec`:
- Add `report: Optional["RunReport"] = None` (the `RunReport` import already exists from Task 5).
- Change the page call to:

```python
        category = cat_key.split("_", 1)[0]  # "cpu_amd_am4" -> "cpu"
        stats = report.category(category) if report is not None else None
        scraped_products = scrape_all_pages(cat_url, category_path=fallback_path, stats=stats)
```

- Remove the later duplicate `category = cat_key.split(...)` line inside the inner loop.

In `main`, pass `report=report`: `scrape_scorptec(watchlist, only_category=category, report=report)`.

- [ ] **Step 6: Umart telemetry**

Replace `get_max_page` with:

```python
def get_max_page(html: str) -> int:
    """Highest page number linked from a category page (1 when unpaginated)."""
    pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
    if not pages:
        return 1
    highest = max(pages)
    if highest > UMART_MAX_PAGES:
        # The cap used to apply silently, dropping every page past it (#14).
        logger.warning("Umart lists %d pages but UMART_MAX_PAGES is %d - pages %d-%d will not be scraped",
                       highest, UMART_MAX_PAGES, UMART_MAX_PAGES + 1, highest)
    return min(highest, UMART_MAX_PAGES)
```

In `parse_product_grid`:
- Add `stats: Optional[Dict[str, int]] = None`.
- Change the loop to `cards = soup.find_all(class_="goods-item")`, `dropped = 0`, `for card in cards:`.
- In each `continue` branch (the missing sku or price, and the no-name `else`), do `dropped += 1` before the `continue`.
- Before `return products`, add the same `stats` update and WARNING as Scorptec, with the message `"Dropped %d of %d Umart card(s): no id, price or name"`.

Replace `scrape_all_pages` with:

```python
def scrape_all_pages(category_url: str, stats: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Walk every page of one category.

    Page one is fetched first to learn the page count, rather than following
    "next" links, because Umart renders the full pager on every page. Pages
    attempted vs fetched go into ``stats`` so a hole is reported (#14).
    """
    counts = stats if stats is not None else {}
    counts["pages_attempted"] = counts.get("pages_attempted", 0) + 1
    first = fetch_page(category_url)
    if first is None:
        logger.warning("Umart category page 1 failed - category skipped: %s", category_url)
        return []
    counts["pages_fetched"] = counts.get("pages_fetched", 0) + 1

    products = parse_product_grid(first, stats=counts)
    last_page = get_max_page(first)
    logger.info("  page 1/%d: %d products", last_page, len(products))

    for page in range(2, last_page + 1):
        time.sleep(UMART_PAGE_DELAY)
        counts["pages_attempted"] += 1
        html = fetch_page(f"{category_url}?page={page}")
        if html is None:
            # A hole in the middle is not worth abandoning the rest for, but it
            # is no longer silent: the count lands in the run report.
            logger.warning("Umart page %d/%d failed - skipped (%d product(s) so far)",
                           page, last_page, len(products))
            continue
        counts["pages_fetched"] += 1
        page_products = parse_product_grid(html, stats=counts)
        logger.info("  page %d/%d: %d products", page, last_page, len(page_products))
        products.extend(page_products)

    return products
```

In `scrape_umart`:
- Add `report: Optional[RunReport] = None`.
- Call `scrape_all_pages(url, stats=report.category(category) if report is not None else None)`.

In `main`, pass `report=report`.

- [ ] **Step 7: PCCG telemetry**

In `algolia_fetch_catalogue`:
- Add `stats: Optional[Dict[str, int]] = None`, and `from typing import Optional` if it is missing.
- Add `counts = stats if stats is not None else {}` before the `while`.
- At the top of each page iteration (before `for attempt in ...`), add `counts["pages_attempted"] = counts.get("pages_attempted", 0) + 1`.
- Replace `all_products.extend(_extract_products(hits))` with:

```python
                extracted = _extract_products(hits)
                counts["pages_fetched"] = counts.get("pages_fetched", 0) + 1
                counts["cards_seen"] = counts.get("cards_seen", 0) + len(hits)
                counts["cards_dropped"] = counts.get("cards_dropped", 0) + len(hits) - len(extracted)
                if len(extracted) < len(hits):
                    LOGGER.warning("Dropped %d of %d Algolia hit(s) with no product name",
                                   len(hits) - len(extracted), len(hits))
                all_products.extend(extracted)
```

In `scrape_category`:
- Add `report: Optional[RunReport] = None`.
- Call `algolia_fetch_catalogue(category_filter, stats=report.category(category) if report is not None else None)`.

In `main`, call `scrape_category(category, watchlist, report=report)`.

- [ ] **Step 8: Health rules**

In `config.py`, after `DEFAULT_MIN_TOTAL`, add:

```python
# Relative drop rule (#7b, #14): today's listings per retailer and category
# below MATCH_DROP_RATIO of the trailing MATCH_DROP_WINDOW_DAYS median is an
# ERROR. Needs MATCH_DROP_MIN_HISTORY prior days; below that the static
# MATCH_THRESHOLDS are the cold-start fallback. PCCG had 54 against ~121 on
# 25-Aug and passed the static floor of 20.
MATCH_DROP_RATIO = _env_float("TRACKAROO_MATCH_DROP_RATIO", 0.6)
MATCH_DROP_WINDOW_DAYS = _env_int("TRACKAROO_MATCH_DROP_WINDOW_DAYS", 7)
MATCH_DROP_MIN_HISTORY = _env_int("TRACKAROO_MATCH_DROP_MIN_HISTORY", 3)
```

Add the three to the docstring list, and add them to the `from config import (...)` in `health_checks.py`, with `import statistics` at the top. Then add, after `check_match_count_anomalies`:

```python
UNPARSED_CARD_RATIO = 0.10


def check_run_report(report: dict) -> list[CheckResult]:
    """Scraper telemetry (scraper/run_report.py) -> health results (#14).

    - a page fetched but no product cards on it: ERROR, selector drift;
    - more than 10% of cards unparseable: ERROR, drift likely;
    - fewer pages fetched than attempted: WARNING, a pagination hole.
    """
    results: list[CheckResult] = []
    retailer = report.get("retailer", "unknown")
    for category, c in sorted((report.get("categories") or {}).items()):
        where = f"{retailer}/{category}"
        attempted = c.get("pages_attempted", 0)
        fetched = c.get("pages_fetched", 0)
        seen = c.get("cards_seen", 0)
        dropped = c.get("cards_dropped", 0)
        if fetched and not seen:
            results.append(CheckResult(
                f"selector_drift_{retailer}_{category}", CheckResult.ERROR,
                f"selector drift at {where}: {fetched} page(s) fetched but 0 product cards "
                f"found - the retailer's markup probably changed",
            ))
        elif seen and dropped / seen > UNPARSED_CARD_RATIO:
            results.append(CheckResult(
                f"unparsed_cards_{retailer}_{category}", CheckResult.ERROR,
                f"{where}: {dropped} of {seen} product cards could not be parsed - selector drift likely",
            ))
        if fetched < attempted:
            results.append(CheckResult(
                f"pagination_hole_{retailer}_{category}", CheckResult.WARNING,
                f"pagination hole at {where}: fetched {fetched} of {attempted} page(s)",
            ))
    return results


def check_match_count_drop(
    db_path: Optional[Path] = None,
    today: Optional[date] = None,
) -> list[CheckResult]:
    """Today's listing count per retailer and category vs its trailing median (#7b).

    The static thresholds sit far below normal volume, so a half-empty day
    passed. A retailer with no rows today is skipped: check_today_coverage
    reports that. Fewer than MATCH_DROP_MIN_HISTORY prior days: not judged.
    """
    if db_path is None:
        db_path = DB_PATH
    if not Path(db_path).exists():
        return []
    today = today or date.today()
    end = today.strftime(DB_DATE_FORMAT)
    start = (today - timedelta(days=MATCH_DROP_WINDOW_DAYS)).strftime(DB_DATE_FORMAT)

    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute("""
            SELECT rl.retailer, p.category, ps.snapshot_date, COUNT(DISTINCT rl.id)
            FROM price_snapshots ps
            JOIN retailer_listings rl ON rl.id = ps.retailer_listing_id
            JOIN products p ON p.id = rl.product_id
            WHERE ps.snapshot_date BETWEEN ? AND ?
            GROUP BY rl.retailer, p.category, ps.snapshot_date
        """, (start, end)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    series: dict = {}
    for retailer, category, day, n in rows:
        series.setdefault((retailer, category), {})[day] = n

    results: list[CheckResult] = []
    for (retailer, category), by_day in sorted(series.items()):
        today_n = by_day.get(end)
        prior = [n for day, n in by_day.items() if day != end]
        if today_n is None or len(prior) < MATCH_DROP_MIN_HISTORY:
            continue
        median = statistics.median(prior)
        name = f"match_drop_{retailer}_{category}"
        if today_n < MATCH_DROP_RATIO * median:
            results.append(CheckResult(
                name, CheckResult.ERROR,
                f"{retailer}/{category}: {today_n} listings today vs a trailing "
                f"{MATCH_DROP_WINDOW_DAYS}-day median of {median:g} ({today_n / median:.0%}; "
                f"alert below {MATCH_DROP_RATIO:.0%})",
            ))
        else:
            results.append(CheckResult(
                name, CheckResult.OK,
                f"{retailer}/{category}: {today_n} listings today (median {median:g})",
            ))
    return results
```

In `run_all_checks`, after the match-count-anomalies block, add:

```python
    LOGGER.info("\n--- Match Count Drop (vs trailing median) ---")
    drop_results = check_match_count_drop(db_path)
    all_results.extend(drop_results)
    for r in drop_results:
        LOGGER.info("  %s", r)
```

- [ ] **Step 9: Wire the rules into `run_daily`**

- Add `check_match_count_drop, check_run_report` to the `health_checks` import.
- In `_db_checks()`, after the anomalies entry, add `("check_match_count_drop", lambda: check_match_count_drop(DB_PATH)),`.
- In `run()`, directly after the `if not args.dry_run: best_effort("Recording scrape runs", ...)` line, add:

```python
    report_results: List[CheckResult] = []
    if not args.no_health:
        report_results = [r for o in results.values() if o.report for r in check_run_report(o.report)]
        _report_results(report_results, "Scrape telemetry")
```

- Change `failed = health_errors(json_results, ingest_results, db_results)` to `failed = health_errors(json_results, report_results, ingest_results, db_results)`.

- [ ] **Step 10: Run the tests**

Run: `python -m pytest unit_testing/test_scraper_fixtures.py unit_testing/test_health_checks.py unit_testing/test_scraper.py unit_testing/test_umart.py unit_testing/test_pccg_query_budget.py unit_testing/test_pccg_reliability.py unit_testing/test_run_report.py unit_testing/test_export_snapshots.py -q`

Expected: all PASS. `check_json_db_parity` is untouched, because telemetry lives in the run report and not in the snapshot envelope.

- [ ] **Step 11: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add unit_testing/fixtures/ unit_testing/test_scraper_fixtures.py unit_testing/test_health_checks.py unit_testing/test_scraper.py scraper/scorptec.py scraper/umart.py scraper/pccg.py health_checks.py config.py run_daily.py
git commit -m "feat(scrapers): page/card telemetry, real-HTML fixtures, selector-drift and match-drop alerts (#14, #7b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: GitHub Actions CI that never scrapes (#13, plus the Phase 2 node smoke-test follow-up)

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `web/e2e/write-synthetic-data.mjs`
- Modify: `web/e2e/seed.mjs:57` (export `buildSyntheticSources`)
- Modify: `web/test/helpers/seed.ts:10, 53-57` (honour `TRACKAROO_DATA_DIR`; tolerate a missing dir)
- Modify: `deploy/entrypoint-single.sh` (the `SKIP_PIPELINE` knob)
- Modify: `unit_testing/conftest.py` (the no-network guard)
- Create: `unit_testing/test_ci_guards.py`

**Interfaces:**
- Consumes: the `run_pipeline --pending-only` entrypoint shape (Task 4).
- Produces: the env knob `SKIP_PIPELINE=1`, which runs dashboard only (no boot catch-up, no scheduler, no spec sync, no staleness loop). Also the script `node web/e2e/write-synthetic-data.mjs <dir>`, and an autouse pytest fixture `_no_network` that raises `RuntimeError("Blocked outbound connection ...")` on any non-loopback AF_INET/AF_INET6 `connect`.

- [ ] **Step 1: Write the failing tests**

Create `unit_testing/test_ci_guards.py`:

```python
"""Guards that keep tests and CI from ever touching a retailer (#13)."""
import socket
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_the_suite_blocks_outbound_connections():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Blocked outbound connection"):
            s.connect(("93.184.216.34", 80))
    finally:
        s.close()


def test_loopback_is_still_allowed():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()


def test_skip_pipeline_stops_before_any_scrape():
    text = (REPO / "deploy" / "entrypoint-single.sh").read_text(encoding="utf-8")
    knob = text.index('if [ "${SKIP_PIPELINE:-0}" = "1" ]')
    assert knob < text.index("run_pipeline --pending-only")
    assert knob < text.index("spec_sync_loop &")
    assert knob > text.index("node web/server.js &")


def test_ci_workflow_boots_the_image_offline():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--network none" in ci
    assert "SKIP_PIPELINE=1" in ci
    assert "python -m pytest -q" in ci
    assert "npm run test:e2e" in ci
    assert "node server.js" in ci
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_ci_guards.py -q`

Expected: FAIL. The connect is not blocked (it errors or times out with no network, or connects), and `ci.yml` and the `SKIP_PIPELINE` string are missing.

- [ ] **Step 3: The no-network guard**

In `unit_testing/conftest.py`, add `import socket` and, after the imports:

```python
# ── No real network, ever (#13) ──────────────────────────────────────
# Tests must mock HTTP. Any connect() to a non-loopback address fails loudly
# naming the address, so a test that would have scraped a retailer (or posted
# to Discord from a developer's .env) cannot pass by accident. Loopback stays
# open for tests that run a local server; AF_UNIX is untouched.
_REAL_CONNECT = socket.socket.connect
_LOOPBACK = ("127.", "::1", "localhost")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def guarded(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            host = str(address[0])
            if not host.startswith(_LOOPBACK):
                raise RuntimeError(f"Blocked outbound connection to {address!r}: tests must mock HTTP")
        return _REAL_CONNECT(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
```

Run `python -m pytest -q`.

Expected: PASS. If a test now fails with `Blocked outbound connection`, that test was making a real request. Mock the call it makes (`monkeypatch.setattr("<module>.requests.get", ...)` or `.post`, as in `test_pccg_reliability.py`) rather than weakening the guard.

- [ ] **Step 4: `SKIP_PIPELINE`**

In `deploy/entrypoint-single.sh`, add to the knobs comment:

```sh
#   SKIP_PIPELINE        1 = dashboard only: no boot catch-up, no scheduler, no
#                        spec sync, no staleness loop -- nothing ever scrapes.
#                        Used by CI's boot smoke test (--network none).
```

Directly after `log "Dashboard started."`, and before the `RUN_ONCE` block, add:

```sh
if [ "${SKIP_PIPELINE:-0}" = "1" ]; then
    log "SKIP_PIPELINE=1 - dashboard only: no catch-up, no scheduler, no scraping."
    wait "$WEB_PID"
    exit $?
fi
```

Run: `sh -n deploy/entrypoint-single.sh`

Expected: no output.

- [ ] **Step 5: Synthetic data for CI**

In `web/e2e/seed.mjs:57`, change `function buildSyntheticSources()` to `export function buildSyntheticSources()`. The `if (process.argv[1] ...)` main guard keeps imports side-effect free.

Create `web/e2e/write-synthetic-data.mjs`:

```js
// Writes the deterministic synthetic snapshots (the same ones e2e/seed.mjs
// falls back to) as data/*.json files. CI has no data/ -- it is gitignored --
// and the vitest helper seeds from it (#13).
//   node e2e/write-synthetic-data.mjs ../data
import fs from 'node:fs';
import path from 'node:path';
import { buildSyntheticSources } from './seed.mjs';

const out = path.resolve(process.argv[2] ?? path.join('..', 'data'));
fs.mkdirSync(out, { recursive: true });
const existing = fs.readdirSync(out).filter((f) => f.endsWith('.json'));
if (existing.length) {
	// Never mix synthetic files into a real scrape history.
	console.error(`[synthetic] ${out} already holds ${existing.length} JSON file(s) - refusing`);
	process.exit(1);
}
const sources = buildSyntheticSources();
for (const { name, data } of sources) {
	fs.writeFileSync(path.join(out, name), JSON.stringify(data, null, 2));
}
console.log(`[synthetic] wrote ${sources.length} snapshot file(s) to ${out}`);
```

In `web/test/helpers/seed.ts`:
- Replace `export const DATA_DIR = path.resolve(here, '..', '..', '..', 'data');` with:

```ts
// Overridable like the backend's TRACKAROO_DATA_DIR, so CI (no data/) and a
// local check against synthetic data can point elsewhere.
export const DATA_DIR = process.env.TRACKAROO_DATA_DIR
	? path.resolve(process.env.TRACKAROO_DATA_DIR)
	: path.resolve(here, '..', '..', '..', 'data');
```

- In `seedDatabase`, replace `fs.readdirSync(DATA_DIR)` with `(fs.existsSync(DATA_DIR) ? fs.readdirSync(DATA_DIR) : [])`.

- [ ] **Step 6: Prove the suites pass on synthetic data, locally**

From `web/`:

```bash
node e2e/write-synthetic-data.mjs "$TEMP/trackaroo-synth"
TRACKAROO_DATA_DIR="$TEMP/trackaroo-synth" npm test
TRACKAROO_DATA_DIR="$TEMP/trackaroo-synth" npm run test:e2e
```

Expected: all PASS.

If a vitest test fails only because it asserts a fact from the live scrape (a model or date that only real data has), don't delete it. Guard it: add `export const SYNTHETIC = !!process.env.TRACKAROO_DATA_DIR;` to `test/helpers/seed.ts`, then change that test's `it(` to `it.skipIf(SYNTHETIC)(`. Record each one skipped this way in the commit message.

Delete the temp dir afterwards.

- [ ] **Step 7: The workflow**

Create `.github/workflows/ci.yml`:

```yaml
# Trackaroo CI (#13). Three jobs; none of them may touch a retailer:
# - backend: pytest (unit_testing/conftest.py blocks every non-loopback socket);
# - web: svelte-check, vitest, Playwright, then a smoke test of the real
#   production entry (node server.js) against a seeded DB -- e2e itself runs
#   vite dev, so this is the only automated run of server.js;
# - docker: build the image and boot it with --network none and
#   SKIP_PIPELINE=1, so the container cannot scrape even by mistake.
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install -r requirements.txt
      - run: python -m pytest -q

  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '24'
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      # data/ is gitignored (real scrapes); use the synthetic snapshots
      # e2e/seed.mjs already falls back to.
      - run: node e2e/write-synthetic-data.mjs ../data
      - run: npm run check
      - run: npm test
      - run: npx playwright install --with-deps chromium
      - run: npm run test:e2e
      - name: Smoke test the production entry (node server.js)
        run: |
          npm run build
          node e2e/seed.mjs
          TRACKAROO_DB="$PWD/e2e/e2e.db" HOST=127.0.0.1 PORT=3100 node server.js > server.log 2>&1 &
          for i in $(seq 1 30); do
            curl -fsS -o /dev/null http://127.0.0.1:3100/ && break
            sleep 1
          done
          code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3100/)
          cat server.log
          test "$code" = 200
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-test-results
          path: web/test-results
          if-no-files-found: ignore

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # The Dockerfile bakes data/ in as seed history; it is gitignored, so
      # give the build an empty one (bootstrap-data.sh skips an empty dir).
      - run: mkdir -p data
      - run: docker build -t trackaroo:ci .
      - name: Boot smoke test (no network, pipeline disabled)
        run: |
          docker run -d --name trackaroo-ci --network none -e SKIP_PIPELINE=1 trackaroo:ci
          ok=
          for i in $(seq 1 60); do
            if docker exec trackaroo-ci node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.status===200?0:1),()=>process.exit(1))"; then
              ok=1
              break
            fi
            sleep 2
          done
          docker logs trackaroo-ci
          test -n "$ok"
          if docker logs trackaroo-ci 2>&1 | grep -E 'Starting pipeline|Scraping '; then
            echo "The container tried to scrape." >&2
            exit 1
          fi
```

- [ ] **Step 8: Run the tests, build the image, and verify on GitHub**

Run: `python -m pytest unit_testing/test_ci_guards.py unit_testing/test_shell_scripts.py -q`

Expected: all PASS.

Run: `docker build -t trackaroo:ci-test .`

Expected: the build succeeds. Do not run it.

After committing, push the branch and open a draft PR (`gh pr create --draft`).

Expected: three green checks (backend, web, docker). To prove the CR guard, push a throwaway commit to a scratch branch that adds a CR to `deploy/entrypoint.sh`, confirm that `backend` fails in `test_shell_scripts`, then delete the scratch branch.

- [ ] **Step 9: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add .github/workflows/ci.yml web/e2e/write-synthetic-data.mjs web/e2e/seed.mjs web/test/helpers/seed.ts deploy/entrypoint-single.sh unit_testing/conftest.py unit_testing/test_ci_guards.py
git commit -m "ci: GitHub Actions for pytest, vitest, svelte-check, Playwright, node server.js and an offline docker boot (#13)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `/healthz`, Docker HEALTHCHECK, a version stamp, and an opt-in heartbeat (#9)

**Files:**
- Create: `web/src/routes/healthz/+server.ts`
- Create: `web/test/healthz.test.ts`
- Create: `heartbeat.py`
- Create: `unit_testing/test_heartbeat.py`
- Modify: `Dockerfile` (ARG/ENV and HEALTHCHECK), `run_daily.py` (the ping after a complete, clean run), `unit_testing/conftest.py` (fake the ping), `.github/workflows/ci.yml` (the build arg, waiting for healthy, asserting `/healthz`)
- Modify: `DEPLOYMENT.md` ("Health / operational checks"), plus the heartbeat setup

**Interfaces:**
- Consumes: `getRetailerFreshness` (Tasks 3 and 5); `pending_retailers` (Task 4); `isolated_pipeline` (Task 1).
- Produces:
  - `GET /healthz` returns 200 `{ ok: true, version, retailers: [{ retailer, latestSnapshotDate, lastRunAt, lastRunStatus }] }` and `cache-control: no-store`. It returns 503 `{ ok: false, version, error }` when the DB cannot be opened or queried.
  - `heartbeat.ping(url: Optional[str] = None, timeout: int = NOTIFY_TIMEOUT_SECONDS) -> bool`
  - `HEARTBEAT_ENV = "TRACKAROO_HEARTBEAT_URL"`
  - `TRACKAROO_VERSION` is set from `--build-arg GIT_SHA` and defaults to `dev`.

- [ ] **Step 1: Write the failing tests**

Create `web/test/healthz.test.ts`:

```ts
// @vitest-environment node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { openDatabase } from '../src/lib/server/db';
import { SCHEMA_PATH } from './helpers/seed';

let dir: string;

beforeEach(() => {
	dir = fs.mkdtempSync(path.join(os.tmpdir(), 'healthz-'));
	vi.resetModules(); // getDb() caches its connection per module instance
});

afterEach(async () => {
	try {
		(await import('../src/lib/server/db')).getDb().close();
	} catch {
		// never opened
	}
	delete process.env.TRACKAROO_VERSION;
	fs.rmSync(dir, { recursive: true, force: true });
});

function seed(): string {
	const file = path.join(dir, 't.db');
	const db = openDatabase(file, { readonly: false, fileMustExist: false });
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
	db.exec(`INSERT INTO active_retailers (retailer, position) VALUES ('scorptec', 0), ('umart', 1);
		INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Ryzen 5 5600', 1);
		INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x/1', 'active');
		INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, '2026-09-28', 199, 'in_stock');`);
	db.close();
	return file;
}

describe('/healthz (#9)', () => {
	it('reports ok, the version and every active retailer', async () => {
		process.env.TRACKAROO_DB = seed();
		process.env.TRACKAROO_VERSION = 'abc1234';
		const { GET } = await import('../src/routes/healthz/+server');

		const res = GET();

		expect(res.status).toBe(200);
		expect(res.headers.get('cache-control')).toBe('no-store');
		const body = await res.json();
		expect(body).toMatchObject({ ok: true, version: 'abc1234' });
		expect(body.retailers.map((r: { retailer: string; latestSnapshotDate: string | null }) => [r.retailer, r.latestSnapshotDate])).toEqual([
			['scorptec', '2026-09-28'],
			['umart', null]
		]);
	});

	it('says dev when no version was baked in', async () => {
		process.env.TRACKAROO_DB = seed();
		const { GET } = await import('../src/routes/healthz/+server');
		expect((await GET().json()).version).toBe('dev');
	});

	it('returns 503 when the database cannot be opened', async () => {
		process.env.TRACKAROO_DB = path.join(dir, 'missing.db');
		const { GET } = await import('../src/routes/healthz/+server');

		const res = GET();

		expect(res.status).toBe(503);
		expect((await res.json()).ok).toBe(false);
	});
});
```

Create `unit_testing/test_heartbeat.py`:

```python
"""The external heartbeat (#9): opt-in, best-effort, only after a complete day."""
import unittest.mock

import requests

import heartbeat
import run_daily


class TestPing:
    def test_unset_is_a_no_op(self, monkeypatch):
        monkeypatch.delenv(heartbeat.HEARTBEAT_ENV, raising=False)
        called = []
        monkeypatch.setattr(heartbeat.requests, "get", lambda *a, **k: called.append(a))
        assert heartbeat.ping() is False
        assert called == []

    def test_a_configured_url_is_pinged(self, monkeypatch):
        resp = unittest.mock.Mock(status_code=200)
        get = unittest.mock.Mock(return_value=resp)
        monkeypatch.setattr(heartbeat.requests, "get", get)
        assert heartbeat.ping("https://hc-ping.example/uuid") is True
        get.assert_called_once()
        assert get.call_args.args[0] == "https://hc-ping.example/uuid"

    def test_a_failing_endpoint_never_raises(self, monkeypatch):
        def boom(*a, **k):
            raise requests.ConnectionError("down")
        monkeypatch.setattr(heartbeat.requests, "get", boom)
        assert heartbeat.ping("https://hc-ping.example/uuid") is False


def _args(*argv):
    return run_daily.build_parser().parse_args(list(argv))


class TestRunDailyPings:
    def test_a_complete_clean_day_pings(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(label, "ok", 0))
        run_daily.run(_args())
        assert isolated_pipeline.heartbeats == 1

    def test_a_run_with_a_missing_retailer_does_not_ping(self, isolated_pipeline, monkeypatch):
        """#9 acceptance."""
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(
            label, "failed" if label == "umart" else "ok", 1 if label == "umart" else 0))
        run_daily.run(_args())
        assert isolated_pipeline.heartbeats == 0

    def test_the_retry_that_completes_the_day_pings(self, isolated_pipeline, monkeypatch):
        attempts = []

        def scraper(n, m, label):
            attempts.append(label)
            failed = label == "umart" and attempts.count("umart") == 1
            return run_daily.ScrapeOutcome(label, "failed" if failed else "ok", 1 if failed else 0)

        monkeypatch.setattr(run_daily, "run_scraper", scraper)
        run_daily.run(_args())
        run_daily.run(_args("--pending-only"))
        assert isolated_pipeline.heartbeats == 1

    def test_a_dry_run_never_pings(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr(run_daily, "run_scraper", lambda n, m, label: run_daily.ScrapeOutcome(label, "ok", 0))
        run_daily.run(_args("--dry-run"))
        assert isolated_pipeline.heartbeats == 0
```

Append to `unit_testing/test_ci_guards.py`:

```python
def test_dockerfile_has_a_healthcheck_on_healthz_and_a_version_stamp():
    text = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG GIT_SHA=dev" in text
    assert "TRACKAROO_VERSION=$GIT_SHA" in text
    [line] = [l for l in text.splitlines() if l.startswith("HEALTHCHECK")]
    assert "--start-period=5m" in line
    assert "/healthz" in text.split("HEALTHCHECK", 1)[1]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_heartbeat.py unit_testing/test_ci_guards.py -q`, then (from `web/`) `npm test -- healthz`

Expected: FAIL with `ModuleNotFoundError: No module named 'heartbeat'`, `AttributeError: ... heartbeats`, and a failure to resolve `../src/routes/healthz/+server`.

- [ ] **Step 3: `/healthz`**

Create `web/src/routes/healthz/+server.ts`:

```ts
// Liveness + what-is-running probe (#9), used by the Docker HEALTHCHECK, CI's
// boot smoke test and Phase 6's redeploy script.
//
// ok means "this process can open and query the DB". Freshness is reported but
// never turns the check unhealthy: staleness is the heartbeat's and the
// staleness monitor's job, and a stale-but-running container must not be
// restarted by an autoheal watcher.
import { json } from '@sveltejs/kit';
import { getDb } from '$lib/server/db';
import { getRetailerFreshness } from '$lib/server/repos';

const NO_STORE = { 'cache-control': 'no-store' };

export function GET(): Response {
	// Baked in at build time: docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD)
	const version = process.env.TRACKAROO_VERSION || 'dev';
	try {
		const retailers = getRetailerFreshness(getDb()).map((r) => ({
			retailer: r.retailer,
			latestSnapshotDate: r.latestSnapshotDate,
			lastRunAt: r.lastRunAt ?? null,
			lastRunStatus: r.lastRunStatus ?? null
		}));
		return json({ ok: true, version, retailers }, { headers: NO_STORE });
	} catch (e) {
		return json(
			{ ok: false, version, error: e instanceof Error ? e.message : String(e) },
			{ status: 503, headers: NO_STORE }
		);
	}
}
```

- [ ] **Step 4: Dockerfile**

At the end of the runtime stage, directly before `EXPOSE 3000`, add:

```dockerfile
# Build stamp (#9, #3): what is actually running shows in /healthz.
#   docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t trackaroo .
# Declared last so a new SHA only rebuilds this layer.
ARG GIT_SHA=dev
ENV TRACKAROO_VERSION=$GIT_SHA

# /healthz answers 200 once node is up and the DB opens. start-period covers a
# first boot that hydrates the whole snapshot history before node starts.
# Docker only *reports* unhealthy (docker ps); restarting on it needs autoheal
# or an external monitor (Phase 6).
HEALTHCHECK --interval=30s --timeout=5s --start-period=5m --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/healthz').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"
```

- [ ] **Step 5: `heartbeat.py`**

```python
"""Outbound heartbeat for an external dead-man's switch (#9).

After a run that leaves every active retailer with a complete scrape today,
run_daily GETs TRACKAROO_HEARTBEAT_URL -- for example a healthchecks.io check
or an Uptime Kuma "push" monitor set to alert after ~26h of silence. A dead
container, a dead host and a silently partial day all look the same from
outside: no ping. Unset (the default until Phase 6), this does nothing.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from config import NOTIFY_TIMEOUT_SECONDS

LOGGER = logging.getLogger(__name__)

HEARTBEAT_ENV = "TRACKAROO_HEARTBEAT_URL"


def ping(url: Optional[str] = None, timeout: int = NOTIFY_TIMEOUT_SECONDS) -> bool:
    """GET the heartbeat URL. True on a 2xx; never raises.

    Args:
        url: Override for tests; defaults to $TRACKAROO_HEARTBEAT_URL.
        timeout: Seconds before giving up.
    """
    target = url if url is not None else os.environ.get(HEARTBEAT_ENV, "").strip()
    if not target:
        return False
    try:
        r = requests.get(target, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        LOGGER.warning("Heartbeat ping failed: %s", e)
        return False
    LOGGER.info("Heartbeat pinged")
    return True
```

- [ ] **Step 6: Ping from `run_daily` and fake it in tests**

In `run_daily.run()`, replace the final `return RUN_EXIT_DEGRADED if (scraper_lines or failed) else RUN_EXIT_OK` with:

```python
    # ── External heartbeat (#9) ─────────────────────────────────────
    # Only when this run was clean AND every active retailer now has a
    # complete scrape today -- a partial day must stay silent so the
    # external monitor notices. A no-op until TRACKAROO_HEARTBEAT_URL is set.
    if not (scraper_lines or failed or args.dry_run):
        if not pending_retailers(list(ACTIVE_RETAILERS), today_iso):
            import heartbeat
            best_effort("Heartbeat", heartbeat.ping)

    return RUN_EXIT_DEGRADED if (scraper_lines or failed) else RUN_EXIT_OK
```

In `unit_testing/conftest.py`'s `isolated_pipeline`:
- Add `heartbeats=0` to the `SimpleNamespace(...)`.
- Before `return calls`, add:

```python
    def fake_ping(*a, **k):
        calls.heartbeats += 1
        return True

    monkeypatch.setattr("heartbeat.ping", fake_ping)
```

- [ ] **Step 7: CI asserts `/healthz` and the healthy state**

In `.github/workflows/ci.yml`:

(a) In the web job's smoke step, append after `test "$code" = 200`:

```yaml
          curl -fsS http://127.0.0.1:3100/healthz | tee healthz.json
          grep -q '"ok":true' healthz.json
```

(b) Replace the docker job's build and boot steps with:

```yaml
      - run: docker build --build-arg GIT_SHA=${GITHUB_SHA::7} -t trackaroo:ci .
      - name: Boot smoke test (no network, pipeline disabled)
        run: |
          docker run -d --name trackaroo-ci --network none -e SKIP_PIPELINE=1 trackaroo:ci
          status=
          for i in $(seq 1 40); do
            status=$(docker inspect -f '{{.State.Health.Status}}' trackaroo-ci)
            [ "$status" = healthy ] && break
            sleep 10
          done
          docker logs trackaroo-ci
          test "$status" = healthy
          docker exec trackaroo-ci node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>r.json()).then(j=>{console.log(JSON.stringify(j));process.exit(j.ok&&j.version===process.argv[1]?0:1)})" "${GITHUB_SHA::7}"
          if docker logs trackaroo-ci 2>&1 | grep -E 'Starting pipeline|Scraping '; then
            echo "The container tried to scrape." >&2
            exit 1
          fi
```

- [ ] **Step 8: Docs**

In `DEPLOYMENT.md` "## Health / operational checks", replace the first bullet with:

```markdown
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
```

- [ ] **Step 9: Run the tests and build**

Run: `python -m pytest unit_testing/test_heartbeat.py unit_testing/test_ci_guards.py unit_testing/test_retry.py -q`, then (from `web/`) `npm run check && npm test -- healthz`

Expected: all PASS, and 0 svelte-check errors.

Run: `docker build --build-arg GIT_SHA=test123 -t trackaroo:healthz-test .`

Expected: the build succeeds. Do not run it against real data. The CI docker job exercises the HEALTHCHECK offline.

- [ ] **Step 10: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add web/src/routes/healthz/+server.ts web/test/healthz.test.ts heartbeat.py run_daily.py Dockerfile unit_testing/conftest.py unit_testing/test_heartbeat.py unit_testing/test_ci_guards.py .github/workflows/ci.yml DEPLOYMENT.md
git commit -m "feat(ops): /healthz, Docker HEALTHCHECK, build stamp and an opt-in external heartbeat (#9)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Backup integrity, an optional off-host mirror, age-based pruning, and a restore drill (#10)

**Files:**
- Modify: `backup_db.py` (whole module: `quick_check`, `prune_backups`, `mirror_backup`, errors, `main`)
- Modify: `config.py` (`BACKUP_MIRROR_DIR`, `BACKUP_MAX_AGE_HOURS`, the `BACKUP_KEEP` doc)
- Modify: `health_checks.py` (add `check_backups`), `run_daily.py` (backup alerts, `check_backups` in `_db_checks`)
- Create: `restore_drill.py`, `unit_testing/test_restore_drill.py`
- Modify: `unit_testing/test_backup.py` (rewrite `TestRetention`; the missing source now raises `FileNotFoundError`)
- Modify: `DEPLOYMENT.md` "### Backups"

**Interfaces:**
- Consumes: `send_pipeline_alert` and `alerts_enabled` (Task 1); `_db_checks` (Task 1); `isolated_pipeline` (Task 1).
- Produces, in `backup_db`:
  - `BACKUP_NAME_RE`
  - `class BackupIntegrityError(RuntimeError)` and `class BackupMirrorError(RuntimeError)`
  - `quick_check(path: Path) -> str` (returns `"ok"` or the problem)
  - `prune_backups(backup_dir: Path, keep_days: int, today: Optional[date] = None, min_keep: int = MIN_KEEP) -> List[Path]`
  - `mirror_backup(backup: Path, mirror_dir: Path, keep_days: int = DEFAULT_KEEP, today: Optional[date] = None) -> Path`
  - `backup_database(db_path=None, backup_dir=None, keep=DEFAULT_KEEP, mirror_dir=None, today=None) -> Path`, which raises `FileNotFoundError` (no more `SystemExit`), `BackupIntegrityError` or `BackupMirrorError`
- Produces, in `config`: `BACKUP_MIRROR_DIR: Optional[Path]` (None unless `TRACKAROO_BACKUP_MIRROR_DIR` is set) and `BACKUP_MAX_AGE_HOURS = 36`.
- Produces, in `health_checks`: `check_backups(backup_dir=None, now=None, max_age_hours=BACKUP_MAX_AGE_HOURS) -> list[CheckResult]`.
- Produces, in `restore_drill`: `newest_backup(backup_dir: Path) -> Optional[Path]`, `drill(backup: Path, live_db: Path) -> List[str]` (problems; empty means pass) and `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

In `unit_testing/test_backup.py`:
- Change the import to `from backup_db import DEFAULT_KEEP, BackupIntegrityError, BackupMirrorError, backup_database, backup_timestamp, prune_backups, quick_check` and add `from datetime import date`.
- Replace `test_missing_source_exits` with:

```python
    def test_missing_source_raises(self, tmp_path):
        """A missing DB raises, so run_daily's backup handler can alert on it
        (SystemExit escaped its except Exception)."""
        with pytest.raises(FileNotFoundError):
            backup_database(db_path=tmp_path / "does-not-exist.db", backup_dir=tmp_path / "backups")
```

Replace the whole `TestRetention` class with:

```python
class TestRetention:
    """Newest backup per day for keep_days days, plus the min_keep newest (#10)."""

    def _make(self, out, *names):
        out.mkdir(exist_ok=True)
        for n in names:
            (out / n).write_text("x")

    def test_keeps_the_newest_backup_of_each_recent_day(self, tmp_path):
        out = tmp_path / "backups"
        self._make(out, *[f"trackaroo_2026-08-{d}_120000.db" for d in range(10, 16)],
                   "trackaroo_2026-08-15_090000.db")

        pruned = prune_backups(out, keep_days=3, today=date(2026, 8, 15), min_keep=1)

        assert sorted(p.name for p in out.iterdir()) == [
            "trackaroo_2026-08-13_120000.db", "trackaroo_2026-08-14_120000.db",
            "trackaroo_2026-08-15_120000.db",
        ]
        assert len(pruned) == 4

    def test_the_newest_few_survive_a_long_gap(self, tmp_path):
        out = tmp_path / "backups"
        self._make(out, "trackaroo_2026-07-01_040000.db", "trackaroo_2026-07-02_040000.db",
                   "trackaroo_2026-07-03_040000.db")

        assert prune_backups(out, keep_days=14, today=date(2026, 9, 29)) == []

    def test_only_trackaroo_named_files_are_touched(self, tmp_path):
        out = tmp_path / "backups"
        self._make(out, *[f"trackaroo_2026-08-{d}_120000.db" for d in range(10, 16)],
                   "notes.txt", "trackaroo_manual-copy.db")

        prune_backups(out, keep_days=1, today=date(2026, 8, 15), min_keep=1)

        assert (out / "notes.txt").exists()
        assert (out / "trackaroo_manual-copy.db").exists()


class TestIntegrity:
    def test_a_good_backup_passes_quick_check(self, tmp_path):
        src = tmp_path / "src.db"
        _create_source_db(src)
        dest = backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=None)
        assert quick_check(dest) == "ok"

    def test_garbage_fails_quick_check(self, tmp_path):
        bad = tmp_path / "bad.db"
        bad.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
        assert quick_check(bad) != "ok"

    def test_a_failing_check_raises_and_prunes_nothing(self, tmp_path, monkeypatch):
        src = tmp_path / "src.db"
        _create_source_db(src)
        out = tmp_path / "backups"
        out.mkdir()
        old = [out / f"trackaroo_2026-01-0{d}_040000.db" for d in range(1, 6)]
        for p in old:
            p.write_text("x")
        monkeypatch.setattr("backup_db.quick_check", lambda path: "*** in database main *** Page 3: btree corrupt")

        with pytest.raises(BackupIntegrityError):
            backup_database(db_path=src, backup_dir=out, keep=1, mirror_dir=None)
        assert all(p.exists() for p in old)


class TestMirror:
    def test_mirror_copies_and_verifies(self, tmp_path):
        src = tmp_path / "src.db"
        _create_source_db(src)
        mirror = tmp_path / "nas"

        dest = backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=mirror)

        assert quick_check(mirror / dest.name) == "ok"

    def test_a_broken_mirror_keeps_the_local_backup(self, tmp_path):
        src = tmp_path / "src.db"
        _create_source_db(src)
        not_a_dir = tmp_path / "nas"
        not_a_dir.write_text("a file where the mount should be")

        with pytest.raises(BackupMirrorError):
            backup_database(db_path=src, backup_dir=tmp_path / "backups", mirror_dir=not_a_dir)
        assert len(list((tmp_path / "backups").glob("trackaroo_*.db"))) == 1

    def test_no_mirror_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backup_db.BACKUP_MIRROR_DIR", None)
        src = tmp_path / "src.db"
        _create_source_db(src)
        backup_database(db_path=src, backup_dir=tmp_path / "backups")
        assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == ["backups"]
```

Create `unit_testing/test_restore_drill.py`:

```python
"""The restore drill proves the newest backup restores and lost nothing (#10)."""
import sqlite3
from pathlib import Path

import restore_drill
from backup_db import backup_database

SCHEMA = (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text(encoding="utf-8")


def _db(path, snapshots_on_day):
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'X', 1)")
    for i in range(snapshots_on_day):
        conn.execute("INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                     "VALUES (1, 'scorptec', ?, 'active')", (f"https://x/{i}",))
        conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                     "VALUES (?, '2026-09-28', 100, 'in_stock')", (i + 1,))
    conn.commit()
    conn.close()
    return path


def test_a_sound_backup_passes(tmp_path):
    live = _db(tmp_path / "live.db", 3)
    backup = backup_database(db_path=live, backup_dir=tmp_path / "backups", mirror_dir=None)

    assert restore_drill.drill(backup, live) == []
    assert restore_drill.newest_backup(tmp_path / "backups") == backup


def test_a_live_db_with_fewer_rows_than_the_backup_fails(tmp_path):
    backup = backup_database(db_path=_db(tmp_path / "old.db", 3),
                             backup_dir=tmp_path / "backups", mirror_dir=None)
    live = _db(tmp_path / "live.db", 2)

    [problem] = restore_drill.drill(backup, live)
    assert "2026-09-28" in problem


def test_a_corrupt_backup_fails(tmp_path):
    live = _db(tmp_path / "live.db", 1)
    bad = tmp_path / "trackaroo_2026-09-29_040000.db"
    bad.write_bytes(b"not a database")

    [problem] = restore_drill.drill(bad, live)
    assert "quick_check" in problem


def test_main_exits_1_without_backups(tmp_path):
    live = _db(tmp_path / "live.db", 1)
    assert restore_drill.main(["--backup-dir", str(tmp_path / "none"), "--db", str(live)]) == 1


def test_main_exits_0_on_a_sound_backup(tmp_path):
    live = _db(tmp_path / "live.db", 2)
    backup_database(db_path=live, backup_dir=tmp_path / "backups", mirror_dir=None)
    assert restore_drill.main(["--backup-dir", str(tmp_path / "backups"), "--db", str(live)]) == 0
```

Append to `unit_testing/test_health_checks.py`, adding `check_backups` to its imports:

```python
class TestCheckBackups:
    def test_a_recent_backup_is_ok(self, tmp_path):
        (tmp_path / "trackaroo_2026-09-29_040512.db").write_text("x")
        [r] = check_backups(tmp_path, now=datetime(2026, 9, 29, 10, 0))
        assert r.status == CheckResult.OK

    def test_an_old_backup_warns(self, tmp_path):
        (tmp_path / "trackaroo_2026-09-26_040512.db").write_text("x")
        [r] = check_backups(tmp_path, now=datetime(2026, 9, 29, 10, 0))
        assert r.status == CheckResult.WARNING
        assert "trackaroo_2026-09-26_040512.db" in r.message

    def test_no_backups_warns(self, tmp_path):
        [r] = check_backups(tmp_path / "absent", now=datetime(2026, 9, 29, 10, 0))
        assert r.status == CheckResult.WARNING
```

In `unit_testing/test_run_daily_resilience.py`, a backup failure now degrades the run and alerts. It no longer just logs. Replace Task 1's `TestBestEffortSteps.test_backup_crash_does_not_raise` with:

```python
    def test_backup_crash_does_not_raise_but_alerts(self, isolated_pipeline, monkeypatch):
        monkeypatch.setattr("backup_db.backup_database", _boom)
        monkeypatch.setattr(run_daily, "run_scraper", _outcome("ok"))

        assert run_daily.run(_args()) == run_daily.RUN_EXIT_DEGRADED
        assert "backup" in "\n".join(isolated_pipeline.alerts[-1]).lower()
```

and append:

```python
def test_a_backup_integrity_failure_alerts_and_degrades(isolated_pipeline, monkeypatch):
    from backup_db import BackupIntegrityError

    def corrupt(**k):
        raise BackupIntegrityError("trackaroo_x.db failed PRAGMA quick_check: btree corrupt")

    monkeypatch.setattr("backup_db.backup_database", corrupt)
    monkeypatch.setattr(run_daily, "run_scraper", _outcome("ok"))

    assert run_daily.run(_args()) == run_daily.RUN_EXIT_DEGRADED
    assert any("backup" in line.lower() for line in isolated_pipeline.alerts[-1])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_backup.py unit_testing/test_restore_drill.py unit_testing/test_health_checks.py unit_testing/test_run_daily_resilience.py -q`

Expected: FAIL with `ImportError: cannot import name 'BackupIntegrityError'` and `ModuleNotFoundError: No module named 'restore_drill'`.

- [ ] **Step 3: Config**

In `config.py`:
- Change `from typing import Dict` to `from typing import Dict, Optional`.
- After `_env_float`, add:

```python
def _env_optional_path(name: str) -> Optional[Path]:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None
```

Replace the backup-retention block with:

```python
# ── Backup retention and integrity (backup_db.py, #10) ────────────────
# Keep the newest backup of each of the last BACKUP_KEEP *days* (plus the 3
# newest overall). Age-based since 29-Sep-2026: hourly retries and manual runs
# made several backups a day, and keep-the-newest-14 then covered ~11 days.
BACKUP_KEEP = _env_int("TRACKAROO_BACKUP_KEEP", 14)
# Optional off-host copy of every backup (a NAS mount). None = no mirror.
BACKUP_MIRROR_DIR = _env_optional_path("TRACKAROO_BACKUP_MIRROR_DIR")
# check_backups warns when the newest backup is older than this.
BACKUP_MAX_AGE_HOURS = _env_int("TRACKAROO_BACKUP_MAX_AGE_HOURS", 36)
```

Update the docstring: change the `TRACKAROO_BACKUP_KEEP` line to `Days of backups to retain (newest per day) (default: 14)`, and add `TRACKAROO_BACKUP_MIRROR_DIR  Off-host copy of each backup (default: unset = off)` and `TRACKAROO_BACKUP_MAX_AGE_HOURS  Backup-age warning threshold (default: 36)`.

- [ ] **Step 4: Rewrite `backup_db.py`**

```python
"""
Create consistent, verified, timestamped backups of the Trackaroo database.

Uses the SQLite online-backup API (``Connection.backup()``), which produces a
crash-consistent snapshot even while the live database is in WAL mode and
being written. Every new backup is then checked with ``PRAGMA quick_check``;
a failure raises BackupIntegrityError and prunes nothing, so a silently
corrupted DB cannot rotate the good backups out (#10). The online-backup API
copies pages 1:1, so a corrupt live DB yields a failing backup: checking the
backup covers both.

Backups land in ``db/backups/`` (TRACKAROO_BACKUP_DIR) as
``trackaroo_2026-08-15_213000.db``. Retention is by age: the newest backup of
each of the last TRACKAROO_BACKUP_KEEP days, plus the 3 newest overall.
With TRACKAROO_BACKUP_MIRROR_DIR set (a NAS mount), each backup is also
copied there, verified, and pruned by the same rule; unset, nothing leaves
the host.

Usage:
    python backup_db.py                   # Backup to db/backups/, keep 14 days
    python backup_db.py --keep 30         # Keep 30 days
    python backup_db.py --mirror-dir /mnt/nas/trackaroo
    python backup_db.py --db-path db/trackaroo.db --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from config import BACKUP_DIR, BACKUP_KEEP, BACKUP_MIRROR_DIR, BUSY_TIMEOUT_MS, DB_PATH, setup_logging

LOGGER = logging.getLogger(__name__)

DEFAULT_KEEP = BACKUP_KEEP
BACKUP_SUFFIX = ".db"
BACKUP_PREFIX = "trackaroo_"
BACKUP_NAME_RE = re.compile(r"^trackaroo_(\d{4}-\d{2}-\d{2})_(\d{6})\.db$")
MIN_KEEP = 3


class BackupIntegrityError(RuntimeError):
    """A backup failed PRAGMA quick_check. Nothing was pruned (#10)."""


class BackupMirrorError(RuntimeError):
    """The off-host copy failed. The local backup is fine and was kept (#10)."""


def backup_timestamp() -> str:
    """Return the timestamp used in backup filenames (local time)."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def quick_check(path: Path) -> str:
    """``"ok"``, or SQLite's first complaints about ``path``. Opens read-only."""
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        return f"cannot be read: {e}"
    if rows and rows[0][0] == "ok":
        return "ok"
    return "; ".join(str(r[0]) for r in rows[:5]) or "no result"


def prune_backups(
    backup_dir: Path,
    keep_days: int,
    today: Optional[date] = None,
    min_keep: int = MIN_KEEP,
) -> List[Path]:
    """Keep the newest backup of each of the last ``keep_days`` days, plus the
    ``min_keep`` newest overall; delete every other ``trackaroo_*.db``.

    Files that don't match ``trackaroo_YYYY-MM-DD_HHMMSS.db`` are never touched.
    Returns the deleted paths.
    """
    today = today or date.today()
    dated = []
    for p in backup_dir.iterdir():
        m = BACKUP_NAME_RE.match(p.name)
        if not m:
            continue
        try:
            dated.append((p.name, date.fromisoformat(m.group(1)), p))
        except ValueError:
            continue
    dated.sort(key=lambda t: t[0])  # names sort chronologically

    keep = {name for name, _, _ in dated[-min_keep:]} if min_keep > 0 else set()
    newest_per_day = {}
    for name, day, _ in dated:
        newest_per_day[day] = name  # later names overwrite: the newest wins
    cutoff = today - timedelta(days=keep_days)
    keep |= {name for day, name in newest_per_day.items() if day > cutoff}

    pruned = []
    for name, _, path in dated:
        if name not in keep:
            path.unlink()
            pruned.append(path)
    return pruned


def mirror_backup(
    backup: Path,
    mirror_dir: Path,
    keep_days: int = DEFAULT_KEEP,
    today: Optional[date] = None,
) -> Path:
    """Copy ``backup`` into ``mirror_dir`` (atomically), verify it, prune there."""
    mirror_dir.mkdir(parents=True, exist_ok=True)
    target = mirror_dir / backup.name
    tmp = mirror_dir / f".{backup.name}.partial"
    shutil.copy2(backup, tmp)
    os.replace(tmp, target)
    verdict = quick_check(target)
    if verdict != "ok":
        raise BackupIntegrityError(f"mirror copy {target} failed quick_check: {verdict}")
    prune_backups(mirror_dir, keep_days, today=today)
    LOGGER.info("Backup mirrored to %s", target)
    return target


def backup_database(
    db_path: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    keep: int = DEFAULT_KEEP,
    mirror_dir: Optional[Path] = None,
    today: Optional[date] = None,
) -> Path:
    """Back up ``db_path`` into ``backup_dir``, verify it, prune, and mirror.

    Args:
        keep: Days of backups to retain (newest per day).
        mirror_dir: Off-host copy target; defaults to config.BACKUP_MIRROR_DIR
            (None = no mirror).

    Returns:
        Path of the new local backup.

    Raises:
        FileNotFoundError: the source DB does not exist.
        BackupIntegrityError: the new backup failed quick_check (nothing pruned).
        BackupMirrorError: the off-host copy failed (the local backup is kept).
    """
    src = Path(db_path or DB_PATH)
    out_dir = Path(backup_dir or BACKUP_DIR)

    if not src.exists():
        raise FileNotFoundError(f"Database not found at {src}")

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{BACKUP_PREFIX}{backup_timestamp()}{BACKUP_SUFFIX}"

    # A dedicated connection with a busy timeout, so a running writer does
    # not fault the copy; the online-backup API reads without exclusive locks.
    src_conn = sqlite3.connect(str(src))
    src_conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()

    verdict = quick_check(dest)
    if verdict != "ok":
        LOGGER.error("Backup %s FAILED quick_check: %s - nothing pruned", dest, verdict)
        raise BackupIntegrityError(
            f"{dest.name} failed PRAGMA quick_check: {verdict} - older backups kept (nothing pruned)")

    size_mb = dest.stat().st_size / (1024 * 1024)
    LOGGER.info("Backup created: %s (%.2f MB, quick_check ok)", dest, size_mb)

    pruned = prune_backups(out_dir, keep, today=today)
    if pruned:
        LOGGER.info("Pruned %d old backup(s) (keep %d days)", len(pruned), keep)

    target = mirror_dir if mirror_dir is not None else BACKUP_MIRROR_DIR
    if target is not None:
        try:
            mirror_backup(dest, Path(target), keep_days=keep, today=today)
        except (OSError, BackupIntegrityError) as e:
            raise BackupMirrorError(f"Off-host copy to {target} failed: {e}") from e

    return dest


def main(argv: Optional[List[str]] = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Backup the Trackaroo database")
    parser.add_argument("--db-path", type=Path, default=None,
                        help="SQLite database to back up (default: config DB path)")
    parser.add_argument("--backup-dir", type=Path, default=None,
                        help="Directory for backups (default: config backup dir)")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help="Days of backups to retain (default: %(default)s)")
    parser.add_argument("--mirror-dir", type=Path, default=None,
                        help="Also copy the backup here (default: TRACKAROO_BACKUP_MIRROR_DIR)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs without writing any files")
    args = parser.parse_args(argv)

    src = Path(args.db_path or DB_PATH)
    out_dir = Path(args.backup_dir or BACKUP_DIR)

    if args.dry_run:
        LOGGER.info("DRY-RUN: would back up %s -> %s (keep %d days)", src, out_dir, args.keep)
        if not src.exists():
            LOGGER.error("Database not found at %s", src)
            sys.exit(1)
        return

    try:
        backup_database(db_path=src, backup_dir=out_dir, keep=args.keep, mirror_dir=args.mirror_dir)
    except (FileNotFoundError, BackupIntegrityError, BackupMirrorError) as e:
        LOGGER.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

`repair_listings.py:129` calls `backup_database(db_path=args.db)`. A missing DB there now raises `FileNotFoundError` with a traceback instead of `SystemExit(1)`. Run `python -m pytest unit_testing/test_repair_listings.py -q` to confirm it is unaffected.

- [ ] **Step 5: `check_backups`**

In `health_checks.py`, add `BACKUP_MAX_AGE_HOURS` to the config import and add:

```python
def check_backups(
    backup_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
    max_age_hours: float = BACKUP_MAX_AGE_HOURS,
) -> list[CheckResult]:
    """Report the newest DB backup's age (#10).

    Integrity is checked when each backup is taken (backup_db.quick_check, which
    alerts on failure); this catches backups that silently stopped happening.
    """
    from backup_db import BACKUP_NAME_RE
    from config import BACKUP_DIR

    backup_dir = Path(backup_dir or BACKUP_DIR)
    now = now or datetime.now()
    names = sorted(p.name for p in backup_dir.iterdir() if BACKUP_NAME_RE.match(p.name)) \
        if backup_dir.is_dir() else []
    if not names:
        return [CheckResult("backup_age", CheckResult.WARNING, f"No database backups in {backup_dir}")]
    newest = names[-1]
    taken = datetime.strptime(newest[len("trackaroo_"):-len(".db")], "%Y-%m-%d_%H%M%S")
    age_h = (now - taken).total_seconds() / 3600
    if age_h > max_age_hours:
        return [CheckResult("backup_age", CheckResult.WARNING,
                            f"Newest backup {newest} is {age_h:.0f}h old (limit {max_age_hours:.0f}h)")]
    return [CheckResult("backup_age", CheckResult.OK, f"Newest backup {newest} ({age_h:.0f}h old)")]
```

In `run_daily.py`:
- Add `check_backups` to the health_checks import.
- Add `("check_backups", lambda: check_backups()),` at the end of `_db_checks()`.
- In the `finally:` backup block, replace `best_effort("Database backup", backup_database, keep=BACKUP_KEEP)` with:

```python
            try:
                backup_database(keep=BACKUP_KEEP)
            except Exception as e:  # noqa: BLE001 - never breaks the run, always pages
                LOGGER.exception("Database backup failed")
                backup_failed = True
                if alerts_enabled(args):
                    send_pipeline_alert([f"- **Database backup problem**: {e}"])
```

- Initialise `backup_failed = False` next to `failed: List[CheckResult] = []`.
- Change both final `return RUN_EXIT_DEGRADED if (scraper_lines or failed) else RUN_EXIT_OK` expressions (the one after the heartbeat) to `... if (scraper_lines or failed or backup_failed) else ...`. The heartbeat condition stays as it is: a backup problem alerts on its own and does not mean prices were missed.

- [ ] **Step 6: `restore_drill.py`**

```python
"""Restore drill: prove the newest backup restores, and that nothing was lost (#10).

Copies the newest db/backups/trackaroo_*.db to a temp file -- the live DB is
only ever opened read-only -- and checks:
  1. PRAGMA quick_check on the restored copy says ok;
  2. products, retailer_listings and price_snapshots are not empty;
  3. for every snapshot_date in the backup, the live DB holds at least as many
     snapshots (Trackaroo never deletes price data, so fewer means loss).
Exit 0 when all hold, 1 otherwise. Run it monthly; DEPLOYMENT.md -> Backups.

    python restore_drill.py
    python restore_drill.py --backup db/backups/trackaroo_2026-09-28_040512.db
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from backup_db import BACKUP_NAME_RE, quick_check
from config import BACKUP_DIR, DB_PATH, setup_logging

LOGGER = logging.getLogger(__name__)

TABLES = ("products", "retailer_listings", "price_snapshots")


def newest_backup(backup_dir: Path) -> Optional[Path]:
    if not backup_dir.is_dir():
        return None
    names = sorted(p.name for p in backup_dir.iterdir() if BACKUP_NAME_RE.match(p.name))
    return backup_dir / names[-1] if names else None


def _per_day(conn: sqlite3.Connection) -> Dict[str, int]:
    return dict(conn.execute(
        "SELECT snapshot_date, COUNT(*) FROM price_snapshots GROUP BY snapshot_date").fetchall())


def drill(backup: Path, live_db: Path) -> List[str]:
    """Restore ``backup`` to a temp file and compare it with ``live_db``.

    Returns:
        Problems found; an empty list means the drill passed.
    """
    problems: List[str] = []
    with tempfile.TemporaryDirectory(prefix="trackaroo-drill-") as tmp:
        restored = Path(tmp) / "restored.db"
        shutil.copy2(backup, restored)
        verdict = quick_check(restored)
        if verdict != "ok":
            return [f"quick_check failed on the restored copy of {backup.name}: {verdict}"]
        conn = sqlite3.connect(str(restored))
        try:
            for table in TABLES:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                LOGGER.info("  %-18s %d rows", table, n)
                if n == 0:
                    problems.append(f"{table} is empty in {backup.name}")
            restored_days = _per_day(conn)
        finally:
            conn.close()

    live = sqlite3.connect(f"file:{live_db.as_posix()}?mode=ro", uri=True)
    try:
        live_days = _per_day(live)
    finally:
        live.close()

    short = [d for d, n in sorted(restored_days.items()) if live_days.get(d, 0) < n]
    if short:
        problems.append(
            f"the live DB holds fewer snapshots than {backup.name} on {len(short)} day(s): "
            f"{', '.join(short[:5])}")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Restore the newest backup to a temp file and verify it")
    parser.add_argument("--backup", type=Path, default=None, help="A specific backup file")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Default: config BACKUP_DIR")
    parser.add_argument("--db", type=Path, default=None, help="Live DB (read-only). Default: config DB_PATH")
    args = parser.parse_args(argv)

    backup = args.backup or newest_backup(Path(args.backup_dir or BACKUP_DIR))
    if backup is None:
        LOGGER.error("No backups found in %s", args.backup_dir or BACKUP_DIR)
        return 1
    live = Path(args.db or DB_PATH)
    if not live.exists():
        LOGGER.error("Live DB not found at %s", live)
        return 1

    LOGGER.info("Restore drill: %s", backup)
    problems = drill(Path(backup), live)
    for p in problems:
        LOGGER.error("  FAIL: %s", p)
    if problems:
        return 1
    LOGGER.info("Restore drill passed: %s restores cleanly and the live DB has lost nothing since.",
                Path(backup).name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The Dockerfile's `COPY *.py ./` already ships `restore_drill.py` and `heartbeat.py`.

- [ ] **Step 7: Docs**

Replace `DEPLOYMENT.md` "### Backups" (`:170-176`) with:

```markdown
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
  It is unset by default, and Phase 6 switches it on. A mirror failure alerts
  but keeps the local backup.
- **Health:** `check_backups` warns when the newest backup is older than
  `TRACKAROO_BACKUP_MAX_AGE_HOURS` (default 36).

`data/*.json` (the rebuild source) is not mirrored by this. Phase 6 covers it
with the host-level backup of the project directory.

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
```

- [ ] **Step 8: Run the tests**

Run: `python -m pytest unit_testing/test_backup.py unit_testing/test_restore_drill.py unit_testing/test_health_checks.py unit_testing/test_run_daily_resilience.py unit_testing/test_repair_listings.py unit_testing/test_health_checks_backup.py -q`

Expected: all PASS.

- [ ] **Step 9: Run the drill against a scratch copy (never the live file)**

```bash
mkdir -p "$TEMP/drill/backups" && cp db/trackaroo.db "$TEMP/drill/live.db"
TRACKAROO_BACKUP_DIR="$TEMP/drill/backups" python backup_db.py --db-path "$TEMP/drill/live.db"
python restore_drill.py --backup-dir "$TEMP/drill/backups" --db "$TEMP/drill/live.db"; echo "exit=$?"
```

Expected: `Restore drill passed` and `exit=0`. Then `rm -rf "$TEMP/drill"`, and confirm with `git status` that `db/` is untouched.

- [ ] **Step 10: Gate and commit**

```bash
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && cd ..
git add backup_db.py restore_drill.py config.py health_checks.py run_daily.py unit_testing/test_backup.py unit_testing/test_restore_drill.py unit_testing/test_health_checks.py unit_testing/test_run_daily_resilience.py DEPLOYMENT.md
git commit -m "feat(backup): quick_check every backup, age-based retention, opt-in off-host mirror, restore drill (#10)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Close out: env-var docs, the `PRICE_MOVE_PCT` doc fix (#15), full gate, STATUS

**Files:**
- Modify: `DEPLOYMENT.md` (the env-var table, exit codes, staleness, retry, native cron)
- Modify: `.env.example` (every new var, commented out)
- Modify: `config.py:27` and `.env.example:29` (`PRICE_MOVE_PCT` default 0.20 -> 0.10), `unit_testing/test_health_checks.py` (the docstring `(0.20)` -> `(0.10)`)
- Modify: `CLAUDE.md` (the four pipeline conventions this phase changed)
- Modify: `STATUS.md`

**Interfaces:**
- Consumes: everything above. Produces documentation only.

- [ ] **Step 1: The `PRICE_MOVE_PCT` doc drift (#15, item 1)**

The code default is `0.10`, and `config.py:166-172` explains why (the +10.5% and +12.1% steps). The docs are what is wrong.
- In `config.py:27`, change `(default: 0.20)` to `(default: 0.10)`.
- In `.env.example:29`, change `(default 0.20)` to `(default 0.10)`.
- In `unit_testing/test_health_checks.py`, change the docstring `"""PRICE_MOVE_PCT is a fraction (0.20), not a percentage (20)."""` to `(0.10)`.

- [ ] **Step 2: `.env.example` additions**

Append:

```sh
# ── Scheduling & retry (deploy/entrypoint*.sh, run_daily.py) ──────────
# RUN_AT_HOUR=4            Daily run hour, local 0-23
# RETRY_UNTIL_HOUR=9       Failed/incomplete retailers retried hourly until this hour (inclusive).
#                          Keep it EARLIER than STALENESS_CHECK_HOUR.
# SKIP_PIPELINE=0          1 = dashboard only, never scrapes (CI boot test)

# ── Health thresholds added 29-Sep-2026 (config.py) ───────────────────
# TRACKAROO_MATCH_DROP_RATIO=0.6          ERROR when today's listings < ratio x trailing median
# TRACKAROO_MATCH_DROP_WINDOW_DAYS=7      Trailing window for that median
# TRACKAROO_MATCH_DROP_MIN_HISTORY=3      Prior days needed before the rule judges

# ── Off-host monitoring and backups (OFF until Phase 6) ───────────────
# TRACKAROO_HEARTBEAT_URL=https://hc-ping.com/<uuid>   pinged after a complete, clean day
# TRACKAROO_BACKUP_MIRROR_DIR=/mnt/nas/trackaroo       verified copy of every DB backup
# TRACKAROO_BACKUP_MAX_AGE_HOURS=36                    backup-age warning threshold
```

Also change `.env.example:52`'s `TRACKAROO_BACKUP_KEEP` line to `Days of DB backups to retain, newest per day (default 14)`.

- [ ] **Step 3: DEPLOYMENT.md**

(a) Replace the settings table at `:82-88` with:

```markdown
| Setting | Default | Override |
|---|---|---|
| Daily run hour (local) | `04` | `-e RUN_AT_HOUR=6` |
| Last hourly retry of a failed retailer | `09` | `-e RETRY_UNTIL_HOUR=8` (keep it before `STALENESS_CHECK_HOUR`) |
| Staleness monitor hour | `10` | `-e STALENESS_CHECK_HOUR=11` |
| Timezone | `Australia/Melbourne` | `-e TZ=Europe/Berlin` |
| Backups retained (days, newest per day) | 14 | `-e TRACKAROO_BACKUP_KEEP=30` |
| Dashboard host port | 3000 | `-p 8080:3000` |
| Spec-sync day / hour | Sun / 03 | `-e SPEC_SYNC_DOW=1 -e SPEC_SYNC_HOUR=12` |
```

(b) Replace the paragraph after it (`:90-93`) with:

```markdown
On boot the container seeds the DB if missing, hydrates a fresh one from the
snapshot history baked into the image (a no-op once snapshots exist), starts
the dashboard, and scrapes **whatever today is still missing**
(`run_daily.py --pending-only`). From then on it calls
`run_daily.py --scheduled` hourly. That runs the pipeline from `RUN_AT_HOUR`
and retries each retailer whose run today failed, timed out, came back empty or
was skipped by a cooldown, until `RETRY_UNTIL_HOUR`. The digest and an
identical alert go out at most once a day. Every real run ends with a verified
DB backup.
```

(c) Add a subsection "### Environment variables added in Phase 3 (29-Sep-2026)" under "## Config reference":

```markdown
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
| `ALGOLIA_APP_ID` / `ALGOLIA_API_KEY` | code default | Now commented out in `.env.example`; set only per "PCCG key rotation" | on rotation |
```

(d) In "## Health / operational checks", replace the "Pipeline health" bullet with:

```markdown
- Pipeline health: `run_daily.py` exits `0` when the run was clean (a PCCG
  cooldown skip counts as clean), `1` when nothing could be scraped or the run
  crashed, and `2` when some scraper or health check failed or the backup had
  a problem. Good data is still kept and backed up. Scrapers exit `0` ok,
  `2` incomplete, `3` skipped (cooldown), `4` credentials rejected. Every run
  also writes one `scrape_runs` row per retailer, and the homepage health strip
  shows its time.
```

(e) In "## Staleness monitor", replace the severity table and the "Default threshold is **1 day**" paragraph with:

```markdown
| Condition | Status | Effect |
|---|---|---|
| DB missing, unreadable, or empty | ERROR | exit 1 + Discord alert |
| No data today at all | ERROR | exit 1 + Discord alert |
| Any active retailer with nothing today, or never reported | ERROR | exit 1 + Discord alert |
| PCCG missing today while its cooldown is active | WARNING | logged only |

Default threshold is **0 days**. The monitor runs at `STALENESS_CHECK_HOUR`
(10), after the last retry at `RETRY_UNTIL_HOUR` (9), so by then a missing
day is an outage and it alerts that same morning (#8).
```

(f) In "### PCCG scheduled retry", replace the three-line cron example with:

```cron
# Native equivalent of the container scheduler: hourly, run_daily decides.
0 * * * * cd /opt/trackaroo && /usr/bin/env python3 run_daily.py --scheduled >> logs/cron.log 2>&1
```

Then delete the paragraph that suggests a second one-shot container for PCCG retries, because the container now retries by itself.

- [ ] **Step 4: CLAUDE.md pipeline conventions**

In CLAUDE.md "## Pipeline conventions":

(a) Replace the "Steps after ingest ... are **best-effort**" bullet with:

```markdown
- Steps after ingest (delisted check, JSON mirror, alerts, digest) are
  **best-effort**: route them through `run_daily.best_effort()` (or a
  `try/except` that logs). Health checks go through `guarded_check()`, so a
  crashing check becomes an ERROR result. The backup runs in a `finally`.
```

(b) Add these bullets:

```markdown
- Scrapers exit `0` ok, `2` degraded (a category empty / breaker tripped),
  `3` skipped (cooldown), `4` auth rejected (`scraper/run_report.py`), and
  flush a `RunReport` after **each category**, saving that category's snapshot
  at the same moment. Never go back to one save at the end of `main()`: the
  300 s timeout would cost the whole day (R2).
- The schedule lives in `run_daily.py --scheduled` / `--pending-only`, not in
  the entrypoints. A retailer is done today when its latest `scrape_runs` row
  is `ok`.
- `active_retailers`, `scrape_runs` and `run_markers` are bookkeeping
  tables: DDL in `migrate.py` + `db/schema.sql`, access through
  `pipeline_state.py`.
- `unit_testing/conftest.py` blocks every non-loopback socket. A test that
  trips it was going online: mock it, don't loosen the guard.
```

- [ ] **Step 5: Full gate from a clean tree**

```bash
git status --short          # expect: only the files of this task
python -m pytest -q
cd web && npm run check && npm test && npm run test:e2e && npm run build && cd ..
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t trackaroo:phase3 .
```

Expected: pytest well above 863 passed, 0 failed; svelte-check 0 errors; vitest well above 462; Playwright at least 71 passed; build OK; image builds. Record the exact counts. Do not `docker run` the image. The CI docker job boots it offline, so check that the PR's three checks are green instead.

- [ ] **Step 6: STATUS.md**

Add a dated bullet at the top of "## Recent changes" (no nested "Prior update" chain):

```markdown
- **2026-09-29** — **Phase 3 "robustness" (#12, #7, #8, #11a, #14, #13, #9,
  #10, R1–R4; #15 in part) on `feat/2026-09-29-robustness`.** One exception
  can no longer skip the digest gate, the alerts or the backup, and the all-fail
  path now alerts. A bad JSON file is skipped and reported. Scrapers exit 0/2/3/4,
  so an empty scrape or a rejected PCCG key alerts while a cooldown only warns.
  Every active retailer shows on the health strip ("missing" if never reported)
  with its last scrape time and matched count. Failed retailers are retried
  hourly until `RETRY_UNTIL_HOUR` (9), and the staleness monitor alerts the same
  morning. Scrapers save per category, so a timeout keeps partial results. Page and
  card telemetry, real-HTML fixtures, selector-drift and trailing-median drop
  rules are in. CI: pytest, vitest, svelte-check, Playwright, `node server.js`
  smoke and an offline `docker build` + boot. `/healthz` plus a Docker HEALTHCHECK
  and build stamp. Backups are `quick_check`ed, pruned by age, and have a
  restore drill. **Built but OFF until Phase 6**: `TRACKAROO_HEARTBEAT_URL`,
  `TRACKAROO_BACKUP_MIRROR_DIR`, and the `GIT_SHA` build arg in the redeploy
  script. Gate: pytest **N**, vitest **N**, Playwright **N**, svelte-check
  **0 errors** (fill in from Step 5). **Deploy notes (Phase 6):** `migrate.py`
  (run by bootstrap on boot) adds `active_retailers`, `scrape_runs` and
  `run_markers`. On deploy day, retailers that already have today's snapshots
  are not re-scraped. `TRACKAROO_BACKUP_KEEP` now counts days. Remove
  `ALGOLIA_*` from prod `.env` unless deliberately overriding. **Left in #15**:
  dead Algolia knobs, logs mount + Docker log rotation, requirements split and
  pinning, the run lock, and alert-delete scoping.
```

Replace each **N** with the counts measured in Step 5 before committing.

- [ ] **Step 7: Commit**

```bash
git add DEPLOYMENT.md .env.example config.py CLAUDE.md STATUS.md unit_testing/test_health_checks.py
git commit -m "docs: Phase 3 robustness close-out - env-var table, runbooks, PRICE_MOVE_PCT doc fix (#15)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Hand back to the owner**

Do not comment on or close any GitHub issue. The owner closes them after the Phase 6 prod verification. Report the PR link, the three CI checks, the counts, and the fixture capture date to the owner.

---

## Self-review (run 29-Sep while writing)

**Spec coverage:**

| Requirement | Task(s) |
|---|---|
| #12: wrap best-effort steps | 1 |
| #12: all-fail alert | 1 |
| #12: bad JSON skip, reported as ERROR | 1 |
| #12: backup in `finally` | 1 |
| #12: non-zero exit on degraded, and DEPLOYMENT.md updated | 1, 11 |
| R4: crashing checks | 1 (`guarded_check`) |
| #7(a): exit codes | 2 |
| #7(b): relative drop | 7 |
| #7(c): missing retailer alerts | 2 |
| #7(d): delisted gate | 1 and 2 (outcome `.ok`) |
| #7: Umart thresholds | 2 |
| #7: no clean digest | 2 |
| R1: web lists every active retailer | 3 |
| R1: alert | 2 (`today_coverage`), 4 (staleness) |
| #8: hourly retry until cutoff, per retailer | 4 |
| #8: cooldown respected | 4 (pccg self-skips; `skipped` stays pending) |
| #8: staleness off-by-one, same-day alert | 4 |
| R2: partial results | 5 |
| R3: time + matched per retailer, table and site | 4 (table), 5 (matched + web) |
| #11(a): 401/403 alerting, no cooldown, `.env.example` | 6 |
| #14: fixtures, dropped counts logged, pagination hole, drift ERROR, Scorptec backoff, Umart cap warning | 7 |
| #13: CI jobs, CR check | 8 (test_shell_scripts runs in the backend job) |
| #13: no outbound traffic | 8 (`--network none` + socket guard) |
| #13 / Phase 2 follow-up: `node server.js` smoke | 8, 9 |
| #9: `/healthz` | 9 |
| #9: HEALTHCHECK | 9 |
| #9: version | 9 |
| #9: heartbeat only on a complete day | 9 |
| #9: docs | 9, 11 |
| #10: `quick_check` | 10 |
| #10: no prune on failure | 10 |
| #10: mirror | 10 |
| #10: age pruning | 10 |
| #10: backup-age health | 10 |
| #10: drill + docs | 10 |
| #10: missing DB no longer `SystemExit` | 10 |
| #15: `PRICE_MOVE_PCT` doc | 11 |
| #15: Umart thresholds | 2 |
| #15: rest deferred | 11 (STATUS note) |
| Close-out | 11 |

Gaps left deliberately: #7's full auto-discovery of the PCCG key (#11b), and GFS weekly/monthly backups (D7). Dependabot and branch protection (optional in #13) are left to the owner. Showing the version in the site footer (#3) is Phase 6.

**Placeholder scan:** every code step has code. The two conditional instructions are these:
- Task 8 Step 6 (`it.skipIf(SYNTHETIC)`) gives the exact code and applies it only to tests that fail solely on live-data facts.
- Task 8 Step 3 (mock any test the guard catches) names the exact mocking pattern.

The **N** in the Task 11 STATUS text are counts measured in the step before it.

**Type consistency, checked:**
- `ScrapeOutcome(retailer, status, exit_code, started_at, finished_at, matched, detail, report)` is used the same way in Tasks 1, 2, 4, 5, 6 and 9.
- `status_for_exit`, `SCRAPE_STATUSES` and the `scrape_runs.status` CHECK list the same six values.
- These names are used consistently wherever they appear: `record_scrape_run(... matched=...)`, `retailers_pending(conn, run_date, retailers)`, `pending_retailers(candidates, run_date)`, `claim_marker` / `claim_once`, `RunReport.category()` / `.set()` / `.note()` / `.flush()`, `exit_code_for(report)`, `save_category_snapshot(data_dir, retailer, category, scrape_date, watchlist, products, matched_ids)`, `check_run_report(report)`, `check_match_count_drop(db_path, today)`, `check_backups(backup_dir, now)`, `prune_backups(backup_dir, keep_days, today, min_keep)` and `backup_database(..., mirror_dir, today)`.
- Web: the `RetailerFreshness` optional `lastRun*` fields and `RetailerHealth.detail?` match between `repos.ts`, `health.ts`, `HealthStrip.svelte` and `/healthz`.

**Review Focus:** each of the 5 lines has a named test in its owning task (Tasks 1, 4, 4, 5, and 3+5).
