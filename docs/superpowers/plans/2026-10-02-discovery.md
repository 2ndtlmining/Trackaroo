# New-Part Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell the owner the day a retailer starts selling an in-scope CPU/GPU that Trackaroo does not track, and let them Track or Ignore it from a /discover page.

**Architecture:** Each scraper also writes its full per-category item list to `data/catalogue/`. A best-effort `discover.py` step in `run_daily.py` classifies today's items with the existing chip-key matcher plus a scope table (`discover_rules.py`), upserts one row per untracked part into `discovered_parts`, records conflicts and a run row, and posts new parts to Discord once. A SvelteKit `/discover` page reads those tables and writes Ignore/Track decisions.

**Tech Stack:** Python 3.12 (sqlite3, requests via `notify_discord.send_embed`), pytest; SvelteKit 2 / Svelte 5, better-sqlite3, Tailwind v4, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-02-discovery-design.md` (read it first; this plan argues from it).

## Global Constraints

- Catalogue files live in **`data/catalogue/{retailer}_{category}_{DD_Month_YYYY}.json`**, never at the top of `data/` (spec §4 amendment).
- Catalogue writes never go through `save_snapshot` and never raise into a scraper.
- PCCG makes **exactly 2** Algolia queries per run (`unit_testing/test_pccg_query_budget.py` must stay green unchanged).
- `check_discovery` **never returns ERROR**; discovery runs through `run_daily.best_effort`.
- A run never overwrites `status`, `notified_at` or `decided_at` (except the automatic `untracked|requested → tracked` flip).
- Discord: one embed titled **"New parts at retailers"** to `DISCORD_WEBHOOK_URL`; `notified_at` set only on a 2xx; webhook URLs never logged.
- Status values: `untracked`, `ignored`, `requested`, `tracked`. Actions: `ignore`, `unignore`, `track`, `untrack`.
- Retention: catalogue files 30 days; `discovery_runs` last 30 rows.
- Windows dev box: no unicode arrows in log/console strings (use `->`).
- `tests`: `unit_testing/conftest.py` blocks non-loopback sockets — mock HTTP, never loosen it.
- README.md must gain the "Discovering and adding new parts" section (spec §9); the work is not done without it.

## Review Focus

1. **A catalogue file at the top of `data/`** (an old build, a hand copy): `ingest_today` would treat it as a malformed snapshot. Task 1 pins that `save_catalogue` only ever writes into `data/catalogue/` and Task 2 pins that `ingest_today` ignores a file in that folder.
2. **GPU listing titles without a VRAM size** (e.g. "Gigabyte RTX 5060 Ti Eagle OC") filed correctly by description: they must not show as conflicts. Task 5 has `test_conflict_ignores_title_without_vram`.
3. **Hourly retry runs on the same day** must not re-notify or reset decisions. Task 6 has `test_second_run_same_day_sends_nothing` and Task 5 has `test_upsert_keeps_decisions`.
4. **An old DB that has never run `migrate.py`** (native runs, the web on a stale DB): `discover.run` creates its tables itself (Task 5), and the web helpers return empty data instead of a 500 (Task 7 `missing tables` test).
5. **Discord down / no webhook configured**: nothing is stamped, and the next run retries (Task 6 `test_failed_send_retries_next_run`, `test_no_webhook_is_silent`).

## File Structure

| File | Responsibility |
|---|---|
| `scraper/catalogue_io.py` (new) | Write/read/prune catalogue files |
| `scraper/scorptec.py`, `scraper/umart.py`, `scraper/pccg.py` (modify) | Call `save_catalogue` per category |
| `db/schema.sql`, `migrate.py` (modify) | Three new tables |
| `discover_rules.py` (new) | Pure rules: exclusions, scope/tier, part key, names, suggested row |
| `discover.py` (new) | Orchestration: read catalogues, classify, upsert, conflicts, runs, notify |
| `health_checks.py`, `run_daily.py` (modify) | `check_discovery`; wire the step and the check |
| `web/src/lib/types.ts` (modify), `web/src/lib/server/discover.ts` (new) | Typed reads + status transitions |
| `web/src/routes/discover/+page.server.ts`, `+page.svelte` (new) | The page and its form actions |
| `web/src/lib/nav.ts`, `Header.svelte`, `+layout.server.ts` (modify) | Nav link + pending badge |
| `web/e2e/seed.mjs`, `web/e2e/app.spec.ts`, `web/e2e/mobile.spec.ts` (modify) | Seeded discovery rows + e2e |
| `.dockerignore` (modify) | Keep `data/catalogue/` out of the image |
| `README.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md`, `STATUS.md` (modify) | Guide + conventions |

---

### Task 1: Catalogue file I/O

**Files:**
- Create: `scraper/catalogue_io.py`
- Test: `unit_testing/test_catalogue_io.py`

**Interfaces:**
- Produces:
  - `CATALOGUE_SUBDIR = "catalogue"`
  - `catalogue_dir(data_dir: Path) -> Path`
  - `save_catalogue(data_dir: Path, retailer: str, category: str, file_date: str, items: List[Dict[str, Any]]) -> Optional[Path]` — never raises; None on failure
  - `catalogue_item(title: str, url: str, price_aud: Optional[float], stock_status: str, sku: Optional[str]) -> Dict[str, Any]`
  - `load_catalogues(data_dir: Path, file_date: str) -> Tuple[List[Dict[str, Any]], List[str]]` — (envelopes, unreadable file names)
  - `prune_catalogues(data_dir: Path, keep_days: int = 30, today: Optional[date] = None) -> int`
  - `file_date` is `config.FILE_DATE_FORMAT` (`"%d_%B_%Y"`, e.g. `02_October_2026`)

- [ ] **Step 1: Write the failing tests**

```python
# unit_testing/test_catalogue_io.py
"""Catalogue sidecar files for the discovery report (#16)."""
import json
import os
from datetime import date

from scraper import catalogue_io as cio


def _item(title="MSI RTX 5050 8G", price=389.0):
    return cio.catalogue_item(title, "https://x/1", price, "in_stock", "SKU1")


def test_save_writes_into_catalogue_subfolder(tmp_path):
    path = cio.save_catalogue(tmp_path, "scorptec", "gpu", "02_October_2026", [_item()])
    assert path == tmp_path / "catalogue" / "scorptec_gpu_02_October_2026.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["retailer"] == "scorptec" and body["category"] == "gpu"
    assert body["date"] == "02_October_2026"
    assert body["items"][0] == {
        "title": "MSI RTX 5050 8G", "url": "https://x/1", "price_aud": 389.0,
        "stock_status": "in_stock", "sku": "SKU1",
    }
    # Nothing at the top of data/: ingest globs data/*_{date}.json.
    assert [p.name for p in tmp_path.iterdir()] == ["catalogue"]


def test_save_replaces_same_day_file_even_if_smaller(tmp_path):
    cio.save_catalogue(tmp_path, "pccg", "cpu", "02_October_2026", [_item(), _item("B")])
    path = cio.save_catalogue(tmp_path, "pccg", "cpu", "02_October_2026", [_item()])
    assert len(json.loads(path.read_text(encoding="utf-8"))["items"]) == 1


def test_save_never_raises(tmp_path, monkeypatch, caplog):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(cio.os, "replace", boom)
    assert cio.save_catalogue(tmp_path, "umart", "gpu", "02_October_2026", [_item()]) is None
    assert "catalogue" in caplog.text.lower()
    assert not list((tmp_path / "catalogue").glob("*.tmp"))


def test_load_reads_only_that_day_and_reports_bad_files(tmp_path):
    cio.save_catalogue(tmp_path, "scorptec", "gpu", "02_October_2026", [_item()])
    cio.save_catalogue(tmp_path, "scorptec", "gpu", "01_October_2026", [_item()])
    (tmp_path / "catalogue" / "pccg_gpu_02_October_2026.json").write_text("{nope", encoding="utf-8")
    envelopes, bad = cio.load_catalogues(tmp_path, "02_October_2026")
    assert [(e["retailer"], e["category"]) for e in envelopes] == [("scorptec", "gpu")]
    assert bad == ["pccg_gpu_02_October_2026.json"]


def test_load_with_no_folder_is_empty(tmp_path):
    assert cio.load_catalogues(tmp_path, "02_October_2026") == ([], [])


def test_prune_keeps_30_days(tmp_path):
    for d in ("02_October_2026", "02_September_2026", "01_September_2026"):
        cio.save_catalogue(tmp_path, "umart", "cpu", d, [_item()])
    (tmp_path / "catalogue" / "notes.txt").write_text("keep", encoding="utf-8")
    removed = cio.prune_catalogues(tmp_path, keep_days=30, today=date(2026, 10, 2))
    names = sorted(p.name for p in (tmp_path / "catalogue").iterdir())
    assert removed == 1
    assert names == ["notes.txt", "umart_cpu_02_October_2026.json", "umart_cpu_02_September_2026.json"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_catalogue_io.py -q`
Expected: FAIL — `ImportError: cannot import name 'catalogue_io'`

- [ ] **Step 3: Implement**

```python
# scraper/catalogue_io.py
"""Full per-category item lists for the discovery report (#16).

Every scraper sees far more items than it matches; this keeps them, one file
per (retailer, category, day), so discover.py can say what is on sale that the
watchlist does not track. A report, not a backup: written atomically but NOT
through snapshot_io.save_snapshot (no never-shrink rule), kept 30 days, and
stored in data/catalogue/ -- never the top of data/, because
run_daily.ingest_today globs data/*_{date}.json and the web seeders read every
data/*.json, and would take a catalogue for a malformed snapshot.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)

CATALOGUE_SUBDIR = "catalogue"
_FILE_DATE_FORMAT = "%d_%B_%Y"  # config.FILE_DATE_FORMAT; not imported to keep this leaf-level


def catalogue_dir(data_dir: Path) -> Path:
    return Path(data_dir) / CATALOGUE_SUBDIR


def catalogue_item(
    title: str, url: str, price_aud: Optional[float], stock_status: str, sku: Optional[str]
) -> Dict[str, Any]:
    return {"title": title, "url": url, "price_aud": price_aud, "stock_status": stock_status, "sku": sku}


def save_catalogue(
    data_dir: Path, retailer: str, category: str, file_date: str, items: List[Dict[str, Any]]
) -> Optional[Path]:
    """Write one catalogue file atomically. Never raises: a report must not cost a scrape."""
    target = catalogue_dir(data_dir) / f"{retailer}_{category}_{file_date}.json"
    tmp = target.with_suffix(".json.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "retailer": retailer,
            "category": category,
            "date": file_date,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "items": items,
        }
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
        return target
    except Exception as e:  # noqa: BLE001 - never breaks a scrape
        LOGGER.warning("Could not save the %s %s catalogue (%s); prices are unaffected", retailer, category, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def load_catalogues(data_dir: Path, file_date: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every catalogue for ``file_date``, plus the names of unreadable ones."""
    folder = catalogue_dir(data_dir)
    if not folder.is_dir():
        return [], []
    envelopes: List[Dict[str, Any]] = []
    bad: List[str] = []
    for path in sorted(folder.glob(f"*_{file_date}.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(body.get("items"), list):
                raise ValueError("no items list")
            envelopes.append(body)
        except Exception:  # noqa: BLE001 - one bad file must not hide the rest
            LOGGER.warning("Unreadable catalogue file %s - skipped", path.name)
            bad.append(path.name)
    return envelopes, bad


def prune_catalogues(data_dir: Path, keep_days: int = 30, today: Optional[date] = None) -> int:
    """Delete catalogue files dated more than ``keep_days`` before ``today``."""
    folder = catalogue_dir(data_dir)
    if not folder.is_dir():
        return 0
    cutoff = (today or date.today()) - timedelta(days=keep_days)
    removed = 0
    for path in folder.glob("*.json"):
        stamp = "_".join(path.stem.split("_")[-3:])
        try:
            file_day = datetime.strptime(stamp, _FILE_DATE_FORMAT).date()
        except ValueError:
            continue
        if file_day < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest unit_testing/test_catalogue_io.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scraper/catalogue_io.py unit_testing/test_catalogue_io.py
git commit -m "feat(discovery): catalogue sidecar files in data/catalogue (#16)"
```

---

### Task 2: Scrapers save their catalogues

**Files:**
- Modify: `scraper/scorptec.py` (`main`, ~line 489-516), `scraper/umart.py` (`main`, ~line 293-310), `scraper/pccg.py` (`scrape_category` ~line 599, `main` ~line 717)
- Modify: `.dockerignore`
- Test: `unit_testing/test_catalogue_wiring.py`

**Interfaces:**
- Consumes: `save_catalogue`, `catalogue_item`, `catalogue_dir` (Task 1)
- Produces: `scraper.pccg.scrape_category(category, watchlist, report=None, catalogue_dir=None, file_date=None)` — when both are given, the fetched catalogue is saved; still returns the same 3-tuple. `scraper.scorptec.catalogue_items(scraped: List[dict]) -> List[dict]`, `scraper.umart.catalogue_items(scraped: List[dict]) -> List[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# unit_testing/test_catalogue_wiring.py
"""Each scraper writes its full category list to data/catalogue (#16)."""
import json
from unittest import mock

import pytest

import run_daily
from scraper import pccg, scorptec, umart

SCRAPED = [
    {"name": "Gigabyte RTX 5050 Windforce 8G", "price_aud": 389.0, "stock_status": "in_stock",
     "url": "https://s/1", "retailer_sku": "A1"},
    {"name": "Thermal paste", "price_aud": 9.0, "stock_status": "in_stock",
     "url": "https://s/2", "retailer_sku": None},
]


def test_scorptec_catalogue_items_shape():
    items = scorptec.catalogue_items(SCRAPED)
    assert items[0] == {"title": "Gigabyte RTX 5050 Windforce 8G", "url": "https://s/1",
                        "price_aud": 389.0, "stock_status": "in_stock", "sku": "A1"}
    assert len(items) == 2


def test_umart_catalogue_items_shape():
    assert umart.catalogue_items(SCRAPED)[1]["sku"] is None


def test_scorptec_main_saves_both_categories(tmp_path, monkeypatch):
    monkeypatch.setattr(scorptec, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scorptec, "load_watchlist", lambda: [])
    monkeypatch.setattr(scorptec, "save_category_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(scorptec, "analyze_unmatched", lambda *a, **k: None)
    monkeypatch.setattr(
        scorptec, "scrape_scorptec",
        lambda wl, only_category, report: ([], set(), {f"{only_category}_x": SCRAPED}),
    )
    scorptec.main()
    names = sorted(p.name for p in (tmp_path / "catalogue").iterdir())
    assert [n.split("_")[:2] for n in names] == [["scorptec", "cpu"], ["scorptec", "gpu"]]


def test_umart_main_saves_both_categories(tmp_path, monkeypatch):
    monkeypatch.setattr(umart, "DATA_DIR", tmp_path)
    monkeypatch.setattr(umart, "load_watchlist", lambda: [])
    monkeypatch.setattr(umart, "save_category_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(
        umart, "scrape_umart",
        lambda wl, only_category, report: ([], set(), {only_category: SCRAPED}),
    )
    umart.main()
    assert len(list((tmp_path / "catalogue").glob("umart_*.json"))) == 2


def test_pccg_scrape_category_saves_catalogue_without_extra_query(tmp_path, monkeypatch):
    hits = [{"name": "ASUS RTX 5050 8GB", "price": "$399.00", "url": "https://p/1", "stock_status": "in_stock"}]
    fetch = mock.Mock(return_value=hits)
    monkeypatch.setattr(pccg, "algolia_fetch_catalogue", fetch)
    pccg.scrape_category("gpu", [], catalogue_dir=tmp_path, file_date="02_October_2026")
    assert fetch.call_count == 1
    body = json.loads((tmp_path / "catalogue" / "pccg_gpu_02_October_2026.json").read_text(encoding="utf-8"))
    assert body["items"][0]["title"] == "ASUS RTX 5050 8GB"
    assert body["items"][0]["price_aud"] == 399.0


def test_pccg_scrape_category_without_dir_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(pccg, "algolia_fetch_catalogue", lambda *a, **k: [
        {"name": "x", "price": "$1", "url": "u", "stock_status": "in_stock"}])
    monkeypatch.chdir(tmp_path)
    pccg.scrape_category("gpu", [])
    assert not (tmp_path / "catalogue").exists()


def test_ingest_today_ignores_catalogue_folder(tmp_path, monkeypatch):
    from scraper.catalogue_io import save_catalogue
    save_catalogue(tmp_path, "scorptec", "gpu", "02_October_2026", [])
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    assert run_daily.ingest_today(None, filename="02_October_2026") == {}


def test_dockerignore_excludes_catalogue():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / ".dockerignore").read_text(encoding="utf-8")
    assert "data/catalogue/" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_catalogue_wiring.py -q`
Expected: FAIL — `AttributeError: module 'scraper.scorptec' has no attribute 'catalogue_items'` (and the others)

- [ ] **Step 3: Implement Scorptec**

In `scraper/scorptec.py` add the import next to the other scraper imports:

```python
from scraper.catalogue_io import catalogue_item, save_catalogue
```

Add above `def main()`:

```python
def catalogue_items(scraped: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every scraped card, matched or not, in the catalogue shape (#16)."""
    return [
        catalogue_item(p["name"], p.get("url", ""), p.get("price_aud"), p.get("stock_status", "unknown"),
                       p.get("retailer_sku"))
        for p in scraped
    ]
```

In `main()`, inside the `for category in ("cpu", "gpu"):` loop, directly after the `save_category_snapshot(...)` line:

```python
        save_catalogue(DATA_DIR, "scorptec", category, today,
                       catalogue_items([p for ps in cat_scraped.values() for p in ps]))
```

- [ ] **Step 4: Implement Umart**

In `scraper/umart.py` add the same import and the same `catalogue_items` function (identical body). In `main()` replace

```python
        products, matched_ids, _ = scrape_umart(watchlist, only_category=category, report=report)
```

with

```python
        products, matched_ids, cat_scraped = scrape_umart(watchlist, only_category=category, report=report)
```

and directly after `save_category_snapshot(...)` add:

```python
        save_catalogue(DATA_DIR, "umart", category, today,
                       catalogue_items([p for ps in cat_scraped.values() for p in ps]))
```

- [ ] **Step 5: Implement PCCG**

In `scraper/pccg.py` add `from scraper.catalogue_io import catalogue_item, save_catalogue` and `from pathlib import Path` if not already imported. Change the signature of `scrape_category` to:

```python
def scrape_category(
    category: str,
    watchlist: List[WatchlistProduct],
    report: Optional[RunReport] = None,
    catalogue_dir: Optional[Path] = None,
    file_date: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Set[int], bool]:
```

(keep the existing types used in the file; only the two keyword parameters are new). Directly after the `if not catalogue: ... return [], set(), True` block, add:

```python
    # The discovery report (#16) wants everything on sale, matched or not.
    # The catalogue is already in hand, so this costs no Algolia query.
    if catalogue_dir is not None and file_date is not None:
        save_catalogue(catalogue_dir, "pccg", category, file_date, [
            catalogue_item(p.get("name", ""), p.get("url", ""), _parse_price(p.get("price")) or None,
                           p.get("stock_status", "unknown"), p.get("sku"))
            for p in catalogue
        ])
```

In `main()` change the call to:

```python
            results, matched, tripped = scrape_category(
                category, watchlist, report=report, catalogue_dir=DATA_DIR, file_date=today)
```

- [ ] **Step 6: `.dockerignore`**

Under the `# Data` block add:

```
# Discovery catalogues are a 30-day report, not history to bake into the image.
data/catalogue/
```

- [ ] **Step 7: Run to verify pass, plus the PCCG budget and scraper suites**

Run: `python -m pytest unit_testing/test_catalogue_wiring.py unit_testing/test_pccg_query_budget.py unit_testing/test_scraper.py unit_testing/test_umart.py unit_testing/test_umart_wiring.py unit_testing/test_pccg_reliability.py unit_testing/test_scrape_outcomes.py -q`
Expected: all pass. If an existing test calls `scrape_category` positionally or mocks it with a fixed arity, update the mock to accept `**kwargs` — do not change the 3-tuple return.

- [ ] **Step 8: Commit**

```bash
git add scraper/scorptec.py scraper/umart.py scraper/pccg.py .dockerignore unit_testing/test_catalogue_wiring.py
git commit -m "feat(discovery): scrapers save full category catalogues (#16)"
```

---

### Task 3: Discovery tables

**Files:**
- Modify: `db/schema.sql` (append after `run_markers`), `migrate.py` (new SQL constant + function + call in `main`)
- Test: `unit_testing/test_migrate.py` (new class)

**Interfaces:**
- Produces: tables `discovered_parts`, `discovery_conflicts`, `discovery_runs` (columns below — later tasks use these exact names); `migrate.DISCOVERY_TABLES_SQL: str`; `migrate.migrate_add_discovery_tables(conn, dry_run=False) -> None` (idempotent, create-if-missing per table).

- [ ] **Step 1: Write the failing tests**

Append to `unit_testing/test_migrate.py`:

```python
class TestDiscoveryTables:
    TABLES = ("discovered_parts", "discovery_conflicts", "discovery_runs")

    def _tables(self, conn):
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_creates_all_three_and_is_idempotent(self):
        import sqlite3
        import migrate
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_discovery_tables(conn)
        migrate.migrate_add_discovery_tables(conn)
        assert set(self.TABLES) <= self._tables(conn)

    def test_dry_run_creates_nothing(self):
        import sqlite3
        import migrate
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_discovery_tables(conn, dry_run=True)
        assert not (set(self.TABLES) & self._tables(conn))

    def test_schema_sql_creates_them_too(self, db):
        assert set(self.TABLES) <= self._tables(db)

    def test_status_check_rejects_unknown_status(self):
        import sqlite3
        import migrate
        import pytest
        conn = sqlite3.connect(":memory:")
        migrate.migrate_add_discovery_tables(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen, suggested_row)"
                " VALUES ('gpu', 'rtx 5050|8', 'x', 'maybe', '2026-10-02', '2026-10-02', 'r')")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_migrate.py -q -k Discovery`
Expected: FAIL — `AttributeError: module 'migrate' has no attribute 'migrate_add_discovery_tables'`

- [ ] **Step 3: Implement**

Append to `db/schema.sql` (and paste the identical three `CREATE TABLE` statements into `migrate.py` as `DISCOVERY_TABLES_SQL`):

```sql
-- ─────────────────────────────────────────────────────────────
-- Discovery (#16): parts retailers sell that the watchlist does not track.
-- Written by discover.py (best-effort, after ingest); decisions written by
-- the /discover page. A run never overwrites status/notified_at/decided_at.
-- Keep in step with migrate.DISCOVERY_TABLES_SQL.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE discovered_parts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT    NOT NULL CHECK (category IN ('cpu', 'gpu')),
    part_key        TEXT    NOT NULL,        -- chip key, + '|<vram>' for GPUs ('rtx 5050|8')
    display_name    TEXT    NOT NULL,        -- 'GeForce RTX 5050 8GB'
    status          TEXT    NOT NULL DEFAULT 'untracked'
                    CHECK (status IN ('untracked', 'ignored', 'requested', 'tracked')),
    first_seen      TEXT    NOT NULL,        -- YYYY-MM-DD
    last_seen       TEXT    NOT NULL,        -- YYYY-MM-DD
    listing_count   INTEGER NOT NULL DEFAULT 0,
    retailers       TEXT    NOT NULL DEFAULT '',   -- comma list, e.g. 'pccg,scorptec'
    min_price       REAL,
    min_price_url   TEXT,
    sample_titles   TEXT    NOT NULL DEFAULT '[]', -- JSON array, at most 5
    suggested_row   TEXT    NOT NULL,        -- a db/watchlist.csv line
    notified_at     TEXT,                    -- set once Discord accepted it
    decided_at      TEXT,                    -- last Track/Ignore click
    UNIQUE (category, part_key)
);

CREATE TABLE discovery_conflicts (
    listing_id        INTEGER PRIMARY KEY REFERENCES retailer_listings(id),
    retailer          TEXT    NOT NULL,
    filed_product_id  INTEGER NOT NULL REFERENCES products(id),
    title_key         TEXT,                  -- chip key the title names, NULL if none
    reason            TEXT    NOT NULL,
    title             TEXT    NOT NULL,
    detected_on       TEXT    NOT NULL       -- YYYY-MM-DD
);

CREATE TABLE discovery_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date              TEXT    NOT NULL,  -- YYYY-MM-DD
    finished_at           TEXT    NOT NULL,  -- local 'YYYY-MM-DDTHH:MM:SS'
    catalogue_files       INTEGER NOT NULL,
    missing               TEXT    NOT NULL DEFAULT '[]',  -- JSON ['umart/gpu', ...]
    unrecognised_count    INTEGER NOT NULL DEFAULT 0,
    unrecognised_samples  TEXT    NOT NULL DEFAULT '[]'   -- JSON, at most 20 titles
);
```

In `migrate.py`, after `migrate_add_run_markers_table`:

```python
DISCOVERY_TABLES_SQL = """<the three CREATE TABLE statements above, verbatim>"""


def migrate_add_discovery_tables(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create the discovery tables (#16): additive, create-if-missing per table."""
    statements = [s.strip() for s in DISCOVERY_TABLES_SQL.split(";") if s.strip()]
    for stmt in statements:
        name = stmt.split("CREATE TABLE", 1)[1].split("(", 1)[0].strip()
        if check_table_exists(conn, name):
            LOGGER.info("  [SKIP] %s table already exists", name)
            continue
        if dry_run:
            LOGGER.info("  [DRY-RUN] Would create %s table", name)
            continue
        LOGGER.info("  [MIGRATE] Creating %s table...", name)
        conn.execute(stmt)
        LOGGER.info("  [OK] %s table created", name)
```

In `main()` add after `migrate_add_run_markers_table(conn, dry_run=args.dry_run)`:

```python
        migrate_add_discovery_tables(conn, dry_run=args.dry_run)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest unit_testing/test_migrate.py unit_testing/test_schema.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add db/schema.sql migrate.py unit_testing/test_migrate.py
git commit -m "feat(discovery): discovered_parts, discovery_conflicts, discovery_runs tables (#16)"
```

---

### Task 4: Discovery rules (pure)

**Files:**
- Create: `discover_rules.py`
- Test: `unit_testing/test_discover_rules.py`

**Interfaces:**
- Consumes: `scraper.chip_key.chip_key`, `parse_vram`, `is_excluded`, `normalise`; `db.watchlist.load_watchlist`
- Produces:
  - `is_excluded_title(title: str) -> bool`
  - `series_tier(category: str, key: str) -> Optional[str]` — `'current' | 'current-1' | 'current-2'`, or None when out of scope
  - `part_key(category: str, key: str, vram: Optional[int]) -> str`
  - `brand_for(key: str) -> str`
  - `model_name(category: str, key: str, titles: Sequence[str]) -> str`
  - `display_name(category: str, key: str, vram: Optional[int], titles: Sequence[str]) -> str`
  - `suggested_row(category: str, key: str, vram: Optional[int], titles: Sequence[str], vram_in_model: bool) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# unit_testing/test_discover_rules.py
"""Pure classification rules for discovery (#16)."""
import pytest

import discover_rules as r
from db.watchlist import load_watchlist
from scraper.chip_key import chip_key


@pytest.mark.parametrize("title", [
    "Gigabyte Z890 Ultra 5 Power Bundle", "Gigabyte Aorus RTX 5090 AI Box", "ASUS ROG laptop RTX 5070",
    "Refurbished RTX 4070", "PNY NVIDIA RTX PRO 6000 Blackwell", "AMD Radeon Pro W7800",
    "AMD Ryzen Threadripper 7980X", "Intel Xeon w5-2455X", "AMD EPYC 9654", "Open Box RTX 5080",
])
def test_excluded_titles(title):
    assert r.is_excluded_title(title)


def test_plain_card_not_excluded():
    assert not r.is_excluded_title("MSI GeForce RTX 5050 Ventus 2X OC 8G")


@pytest.mark.parametrize("category,key,tier", [
    ("gpu", "rtx 5050", "current"), ("gpu", "rtx 4060 ti", "current-1"), ("gpu", "rtx 3050", "current-2"),
    ("gpu", "rtx 2060", None), ("gpu", "rtx 6070", "current"),
    ("gpu", "rx 9070 gre", "current"), ("gpu", "rx 7600 xt", "current-1"), ("gpu", "rx 6600", "current-2"),
    ("gpu", "rx 5700 xt", None), ("gpu", "arc b580", "current"), ("gpu", "arc a750", "current-1"),
    ("cpu", "ryzen 9950x3d2", "current"), ("cpu", "ryzen 8600g", "current-1"), ("cpu", "ryzen 7700x3d", "current-1"),
    ("cpu", "ryzen 5600gt", "current-2"), ("cpu", "ryzen 3600", None),
    ("cpu", "ultra 270k plus", "current"), ("cpu", "ultra 225f", "current"), ("cpu", "ultra 155h", None),
    ("cpu", "core 14600kf", "current-1"), ("cpu", "core 13400", "current-2"), ("cpu", "core 12400f", None),
])
def test_series_tier(category, key, tier):
    assert r.series_tier(category, key) == tier


def test_every_watchlist_row_is_in_scope_at_its_own_tier():
    # The scope table must agree with db/watchlist.csv (and so ARCHITECTURE Part 2).
    for wp in load_watchlist():
        key = chip_key(wp["model"], wp["category"])
        assert r.series_tier(wp["category"], key) == wp["gen_tier"], wp["model"]


def test_part_key():
    assert r.part_key("gpu", "rtx 5050", 8) == "rtx 5050|8"
    assert r.part_key("gpu", "rtx 5050", None) == "rtx 5050"
    assert r.part_key("cpu", "ryzen 5600gt", None) == "ryzen 5600gt"


@pytest.mark.parametrize("category,key,titles,name", [
    ("gpu", "rtx 5070 ti super", [], "GeForce RTX 5070 Ti SUPER"),
    ("gpu", "rx 7600 xt", [], "Radeon RX 7600 XT"),
    ("gpu", "rx 9070 gre", [], "Radeon RX 9070 GRE"),
    ("gpu", "arc b570", [], "Arc B570"),
    ("cpu", "ryzen 5600gt", ["AMD Ryzen 5 5600GT Processor"], "Ryzen 5 5600GT"),
    ("cpu", "ryzen 9850x3d", [], "Ryzen 7 9850X3D"),
    ("cpu", "ryzen 8300g", [], "Ryzen 3 8300G"),
    ("cpu", "ultra 270k plus", ["Intel Core Ultra 7 270K Plus"], "Core Ultra 7 270K Plus"),
    ("cpu", "ultra 250k plus", [], "Core Ultra 5 250K Plus"),
    ("cpu", "core 14600kf", [], "Core i5-14600KF"),
    ("cpu", "core 14100", [], "Core i3-14100"),
])
def test_model_name(category, key, titles, name):
    assert r.model_name(category, key, titles) == name


def test_model_name_matches_every_watchlist_row():
    # Generated names round-trip the CSV's own naming for every tracked product
    # (VRAM-suffixed variants excepted -- their VRAM is added separately).
    for wp in load_watchlist():
        key = chip_key(wp["model"], wp["category"])
        name = r.model_name(wp["category"], key, [wp["model"]])
        assert wp["model"].startswith(name), (wp["model"], name)


def test_display_name_adds_vram_for_gpus():
    assert r.display_name("gpu", "rtx 5050", 8, []) == "GeForce RTX 5050 8GB"
    assert r.display_name("gpu", "rtx 5050", None, []) == "GeForce RTX 5050"
    assert r.display_name("cpu", "ryzen 5600gt", None, []) == "Ryzen 5 5600GT"


def test_suggested_rows():
    assert r.suggested_row("gpu", "rtx 5050", 8, [], vram_in_model=False) == \
        'gpu,NVIDIA,GeForce RTX 5050,8GB,current,"geforce rtx 5050|rtx 5050"'
    assert r.suggested_row("gpu", "rtx 5060", 8, [], vram_in_model=True) == \
        'gpu,NVIDIA,GeForce RTX 5060 8GB,8GB,current,"geforce rtx 5060|rtx 5060"'
    assert r.suggested_row("cpu", "ryzen 5600gt", None, [], vram_in_model=False) == \
        'cpu,AMD,Ryzen 5 5600GT,?c,current-2,"ryzen 5 5600gt|ryzen 5600gt"'
    assert r.suggested_row("gpu", "rtx 5050", None, [], vram_in_model=False).split(",")[3] == "?GB"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_discover_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'discover_rules'`

- [ ] **Step 3: Implement**

```python
# discover_rules.py
"""Pure rules for the discovery report (#16): what is excluded, what is in
scope, and how an untracked part is named and turned into a watchlist row.

The scope table mirrors docs/ARCHITECTURE.md Part 2 (current, current-1,
current-2 per product line; Intel Arc all in scope). A series NEWER than the
table (RTX 60, Ryzen 5-digit) counts as in scope at 'current', so a launch
surfaces instead of being silently dropped -- update this table and Part 2
together when that happens. test_discover_rules pins the table to
db/watchlist.csv.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional, Sequence

from scraper.chip_key import is_excluded, normalise

_EXTRA_EXCLUDE = re.compile(
    r"\b(?:refurb\w*|open box|ex demo|demo unit|rtx pro|radeon pro|quadro|threadripper|xeon|epyc|workstation)\b"
)

_GPU_TIERS = {
    "rtx": {5: "current", 4: "current-1", 3: "current-2"},
    "rx": {9: "current", 7: "current-1", 6: "current-2"},
}
_RYZEN_TIERS = {9: "current", 8: "current-1", 7: "current-1", 5: "current-2"}
_CORE_TIERS = {14: "current-1", 13: "current-2"}


def is_excluded_title(title: str) -> bool:
    return is_excluded(title) or bool(_EXTRA_EXCLUDE.search(normalise(title)))


def _digits(text: str) -> str:
    m = re.match(r"[a-z]?(\d+)", text)
    return m.group(1) if m else ""


def series_tier(category: str, key: str) -> Optional[str]:
    family, _, rest = key.partition(" ")
    digits = _digits(rest)
    if not digits and family != "arc":
        return None
    if family in _GPU_TIERS:
        gen = int(digits[:4]) // 1000
        table = _GPU_TIERS[family]
        if gen in table:
            return table[gen]
        return "current" if gen > max(table) else None
    if family == "arc":
        return "current-1" if rest.startswith("a") else "current"
    if family == "ryzen":
        if len(digits) >= 5:
            return "current"
        return _RYZEN_TIERS.get(int(digits) // 1000)
    if family == "ultra":
        series = int(digits) // 100
        return "current" if series >= 2 else None
    if family == "core":
        if len(digits) < 5:
            return None
        gen = int(digits[:2])
        if gen in _CORE_TIERS:
            return _CORE_TIERS[gen]
        return "current" if gen > max(_CORE_TIERS) else None
    return None


def part_key(category: str, key: str, vram: Optional[int]) -> str:
    return f"{key}|{vram}" if category == "gpu" and vram else key


def brand_for(key: str) -> str:
    family = key.split(" ", 1)[0]
    return {"rtx": "NVIDIA", "rx": "AMD", "ryzen": "AMD"}.get(family, "Intel")


def _class_from_titles(titles: Sequence[str], pattern: str) -> Optional[str]:
    found = Counter(m.group(1) for t in titles for m in [re.search(pattern, normalise(t))] if m)
    return found.most_common(1)[0][0] if found else None


def _ryzen_class(code: str) -> str:
    d = int(code[1])
    return "9" if d == 9 else "7" if d >= 7 else "5" if d >= 4 else "3"


def _ultra_class(num: str) -> str:
    t = int(num[1])
    return "5" if t <= 5 else "7" if t <= 7 else "9"


def _core_class(num: str) -> str:
    d = int(num[2])
    return "3" if d <= 3 else "5" if d <= 6 else "7" if d <= 8 else "9"


def model_name(category: str, key: str, titles: Sequence[str]) -> str:
    family, _, rest = key.partition(" ")
    words = rest.split()
    if family == "rtx":
        suffix = {"ti": "Ti", "super": "SUPER"}
        return "GeForce RTX " + " ".join([words[0]] + [suffix[w] for w in words[1:]])
    if family == "rx":
        return "Radeon RX " + " ".join([words[0]] + [w.upper() for w in words[1:]])
    if family == "arc":
        return f"Arc {rest.upper()}"
    if family == "ryzen":
        code = rest.upper()
        cls = _class_from_titles(titles, r"\bryzen ?([3579])\b") or _ryzen_class(code)
        return f"Ryzen {cls} {code}"
    if family == "ultra":
        m = re.match(r"(\d{3})([a-z]*)( plus)?", rest)
        num, suf, plus = m.group(1), m.group(2).upper(), " Plus" if m.group(3) else ""
        cls = _class_from_titles(titles, r"\bultra ?([3579])\b") or _ultra_class(num)
        return f"Core Ultra {cls} {num}{suf}{plus}"
    if family == "core":
        m = re.match(r"(\d{5})([a-z]*)", rest)
        num, suf = m.group(1), m.group(2).upper()
        cls = _class_from_titles(titles, r"\bi([3579])\b") or _core_class(num)
        return f"Core i{cls}-{num}{suf}"
    return key


def display_name(category: str, key: str, vram: Optional[int], titles: Sequence[str]) -> str:
    base = model_name(category, key, titles)
    return f"{base} {vram}GB" if category == "gpu" and vram else base


def suggested_row(
    category: str, key: str, vram: Optional[int], titles: Sequence[str], vram_in_model: bool
) -> str:
    """A db/watchlist.csv line. CPU cores are rarely in shop titles: '?c' is
    filled from the spec source when the row is added (README)."""
    base = model_name(category, key, titles)
    model = f"{base} {vram}GB" if category == "gpu" and vram and vram_in_model else base
    spec = (f"{vram}GB" if vram else "?GB") if category == "gpu" else "?c"
    tier = series_tier(category, key) or "current"
    aliases = "|".join(dict.fromkeys([normalise(base), key]))
    return f'{category},{brand_for(key)},{model},{spec},{tier},"{aliases}"'
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest unit_testing/test_discover_rules.py -q`
Expected: all pass. If `test_every_watchlist_row_is_in_scope_at_its_own_tier` or `test_model_name_matches_every_watchlist_row` fails on a specific CSV row, read that row: the CSV is the authority. Fix the rule (not the CSV) unless the row contradicts ARCHITECTURE Part 2, in which case stop and report it.

- [ ] **Step 5: Commit**

```bash
git add discover_rules.py unit_testing/test_discover_rules.py
git commit -m "feat(discovery): scope table, part naming and suggested watchlist rows (#16)"
```

---

### Task 5: `discover.run` — classify, upsert, conflicts, run record

**Files:**
- Create: `discover.py`
- Test: `unit_testing/test_discover.py`

**Interfaces:**
- Consumes: Task 1 (`load_catalogues`, `prune_catalogues`), Task 3 tables + `migrate.migrate_add_discovery_tables`, Task 4 rules, `scraper.chip_key.Matcher/chip_key/parse_vram`, `db.watchlist.load_watchlist`, `config.ACTIVE_RETAILERS/DATA_DIR/DB_PATH/FILE_DATE_FORMAT`
- Produces: `discover.run(db_path: Path = DB_PATH, data_dir: Path = DATA_DIR, today: Optional[date] = None, notify: bool = False, watchlist: Optional[list] = None) -> Dict[str, Any]` returning `{"catalogue_files": int, "untracked": int, "new_today": int, "conflicts": int, "missing": List[str], "notified": int}`; `discover.notify_new(conn, today_iso: str) -> int` (stub returning 0 in this task, implemented in Task 6).

- [ ] **Step 1: Write the failing tests**

```python
# unit_testing/test_discover.py
"""discover.run end to end against a temp DB and temp catalogues (#16)."""
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import discover
from ingest import init_db
from scraper.catalogue_io import catalogue_item, save_catalogue

TODAY = date(2026, 10, 2)
FD = "02_October_2026"
SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

WATCHLIST = [
    {"category": "gpu", "brand": "AMD", "model": "Radeon RX 9070", "gen_tier": "current", "vram_gb": 16, "cores": None},
    {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5060 Ti", "gen_tier": "current", "vram_gb": 16, "cores": None},
    {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5060 Ti 8GB", "gen_tier": "current", "vram_gb": 8, "cores": None},
    {"category": "cpu", "brand": "AMD", "model": "Ryzen 5 5600", "gen_tier": "current-2", "vram_gb": None, "cores": 6},
]


def _item(title, price=500.0, url=None):
    return catalogue_item(title, url or f"https://shop/{abs(hash(title))}", price, "in_stock", None)


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "t.db"
    conn = init_db(db_path)
    conn.close()
    save_catalogue(tmp_path, "scorptec", "gpu", FD, [
        _item("Made Up RTX 6070 12GB", 999.0),
        _item("Sapphire Pulse RX 9070 GRE 12GB", 849.0),
        _item("Sapphire Pulse RX 9070 GRE 12GB OC", 869.0),
        _item("ASUS Prime RX 9070 16GB", 899.0),          # tracked
        _item("MSI RTX 5060 Ti 8G Ventus", 599.0),         # tracked (8GB row)
        _item("Gigabyte RTX 2060 6GB", 299.0),             # out of scope
        _item("Gigabyte Aorus RTX 5090 AI Box", 9999.0),   # excluded
        _item("Arctic MX-6 thermal paste", 12.0),          # unrecognised
    ])
    save_catalogue(tmp_path, "pccg", "gpu", FD, [_item("PowerColor Reaper RX 9070 GRE 12GB", 829.0)])
    save_catalogue(tmp_path, "scorptec", "cpu", FD, [_item("AMD Ryzen 5 5600GT", 189.0)])
    return tmp_path, db_path


def _run(env, **kw):
    data_dir, db_path = env
    return discover.run(db_path=db_path, data_dir=data_dir, today=kw.pop("today", TODAY),
                        watchlist=WATCHLIST, **kw)


def _parts(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return {r["part_key"]: dict(r) for r in conn.execute("SELECT * FROM discovered_parts")}


def test_fixture_yields_made_up_and_real_parts(env):
    summary = _run(env)
    parts = _parts(env[1])
    assert set(parts) == {"rtx 6070|12", "rx 9070 gre|12", "ryzen 5600gt"}
    gre = parts["rx 9070 gre|12"]
    assert gre["display_name"] == "Radeon RX 9070 GRE 12GB"
    assert gre["listing_count"] == 3 and gre["retailers"] == "pccg,scorptec"
    assert gre["min_price"] == 829.0
    assert gre["first_seen"] == "2026-10-02" and gre["status"] == "untracked"
    assert len(json.loads(gre["sample_titles"])) == 3
    assert summary["untracked"] == 3 and summary["new_today"] == 3


def test_tracked_products_never_appear(env):
    _run(env)
    keys = set(_parts(env[1]))
    assert "rx 9070|16" not in keys
    assert not any(k.startswith("rtx 5060 ti") for k in keys)


def test_run_records_missing_and_unrecognised(env):
    summary = _run(env)
    conn = sqlite3.connect(env[1])
    row = conn.execute("SELECT catalogue_files, missing, unrecognised_count, unrecognised_samples FROM discovery_runs").fetchone()
    assert row[0] == 3
    assert "umart/gpu" in json.loads(row[1]) and "pccg/cpu" in json.loads(row[1])
    assert row[2] == 1 and json.loads(row[3]) == ["Arctic MX-6 thermal paste"]
    assert "umart/cpu" in summary["missing"]


def test_upsert_keeps_decisions(env):
    _run(env)
    conn = sqlite3.connect(env[1])
    conn.execute("UPDATE discovered_parts SET status='ignored', decided_at='2026-10-02T09:00:00', notified_at='x'"
                 " WHERE part_key='ryzen 5600gt'")
    conn.commit()
    _run(env, today=date(2026, 10, 3))  # no catalogues for the 3rd: no upsert
    data_dir, _ = env
    save_catalogue(data_dir, "scorptec", "cpu", "03_October_2026", [_item("AMD Ryzen 5 5600GT", 179.0)])
    _run(env, today=date(2026, 10, 3))
    row = _parts(env[1])["ryzen 5600gt"]
    assert (row["status"], row["decided_at"], row["notified_at"]) == ("ignored", "2026-10-02T09:00:00", "x")
    assert row["last_seen"] == "2026-10-03" and row["min_price"] == 179.0 and row["first_seen"] == "2026-10-02"


def test_requested_part_flips_to_tracked_once_watchlist_has_it(env):
    _run(env)
    conn = sqlite3.connect(env[1])
    conn.execute("UPDATE discovered_parts SET status='requested' WHERE part_key='ryzen 5600gt'")
    conn.commit()
    wl = WATCHLIST + [{"category": "cpu", "brand": "AMD", "model": "Ryzen 5 5600GT", "gen_tier": "current-2",
                       "vram_gb": None, "cores": 6}]
    discover.run(db_path=env[1], data_dir=env[0], today=TODAY, watchlist=wl)
    assert _parts(env[1])["ryzen 5600gt"]["status"] == "tracked"


def test_no_catalogues_keeps_previous_results(env, tmp_path):
    _run(env)
    summary = discover.run(db_path=env[1], data_dir=tmp_path / "empty", today=date(2026, 10, 3), watchlist=WATCHLIST)
    assert summary["catalogue_files"] == 0
    assert len(_parts(env[1])) == 3


def _add_listing(db_path, model, title, vram=None, brand="AMD", category="gpu"):
    conn = sqlite3.connect(db_path)
    pid = conn.execute("INSERT INTO products (category, brand, model, vram_gb, generation_tier) VALUES (?,?,?,?,?)",
                       (category, brand, model, vram, "current")).lastrowid
    lid = conn.execute("INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url) VALUES (?,?,?,?)",
                       (pid, "scorptec", title, f"https://s/{pid}")).lastrowid
    conn.commit()
    return lid


def test_misfiled_listing_is_a_conflict(env):
    lid = _add_listing(env[1], "Radeon RX 9070", "Sapphire Pulse RX 9070 GRE 12GB", vram=16)
    _run(env)
    rows = sqlite3.connect(env[1]).execute("SELECT listing_id, title_key, reason FROM discovery_conflicts").fetchall()
    assert rows == [(lid, "rx 9070 gre", "title names rx 9070 gre, product is rx 9070")]


def test_vram_mismatch_is_a_conflict(env):
    _add_listing(env[1], "GeForce RTX 5060 Ti", "MSI RTX 5060 Ti 8G Ventus", vram=16, brand="NVIDIA")
    _run(env)
    reason = sqlite3.connect(env[1]).execute("SELECT reason FROM discovery_conflicts").fetchone()[0]
    assert reason == "title says 8GB, product is 16GB"


def test_conflict_ignores_title_without_vram(env):
    _add_listing(env[1], "GeForce RTX 5060 Ti", "Gigabyte RTX 5060 Ti Eagle OC", vram=16, brand="NVIDIA")
    _run(env)
    assert sqlite3.connect(env[1]).execute("SELECT COUNT(*) FROM discovery_conflicts").fetchone()[0] == 0


def test_unmatched_placeholders_are_not_conflicts_and_seed_first_seen(env):
    conn = sqlite3.connect(env[1])
    pid = conn.execute("INSERT INTO products (category, brand, model, tracked) VALUES ('cpu','Unmatched','Unmatched CPU listing',0)").lastrowid
    lid = conn.execute("INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url) VALUES (?, 'scorptec', 'amd ryzen 5 5600gt desktop processor', 'https://s/gt')", (pid,)).lastrowid
    conn.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (?, '2026-08-09', 199.0, 'in_stock')", (lid,))
    conn.commit()
    _run(env)
    assert sqlite3.connect(env[1]).execute("SELECT COUNT(*) FROM discovery_conflicts").fetchone()[0] == 0
    assert _parts(env[1])["ryzen 5600gt"]["first_seen"] == "2026-08-09"


def test_creates_its_tables_on_an_old_db(tmp_path):
    db_path = tmp_path / "old.db"
    conn = init_db(db_path)
    for t in ("discovered_parts", "discovery_conflicts", "discovery_runs"):
        conn.execute(f"DROP TABLE {t}")
    conn.commit(); conn.close()
    discover.run(db_path=db_path, data_dir=tmp_path, today=TODAY, watchlist=WATCHLIST)
    names = {r[0] for r in sqlite3.connect(db_path).execute("SELECT name FROM sqlite_master")}
    assert "discovered_parts" in names


def test_prunes_old_catalogues(env):
    data_dir, _ = env
    save_catalogue(data_dir, "umart", "gpu", "01_August_2026", [])
    _run(env)
    assert not (data_dir / "catalogue" / "umart_gpu_01_August_2026.json").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_discover.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'discover'`

- [ ] **Step 3: Implement**

```python
# discover.py
"""Discovery report (#16): parts retailers sell that the watchlist does not track.

Runs from run_daily.py after ingest, through best_effort() -- it can never
break a run. Reads today's data/catalogue/ files (scraper/catalogue_io.py),
classifies every item (discover_rules.py), keeps one discovered_parts row per
untracked part, records listings filed under the wrong product as
discovery_conflicts, and posts parts seen for the first time to Discord once.
A run never overwrites a decision (status/notified_at/decided_at); the only
automatic status change is untracked|requested -> tracked when the watchlist
now resolves the part. See README "Discovering and adding new parts".
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import discover_rules as rules
from config import ACTIVE_RETAILERS, DATA_DIR, DB_PATH, FILE_DATE_FORMAT
from db.watchlist import load_watchlist
from migrate import migrate_add_discovery_tables
from scraper.catalogue_io import load_catalogues, prune_catalogues
from scraper.chip_key import Matcher, chip_key, parse_vram

LOGGER = logging.getLogger(__name__)

CATALOGUE_KEEP_DAYS = 30
RUNS_KEEP = 30
SAMPLE_TITLES = 5
UNRECOGNISED_SAMPLES = 20
HOLDING_BRAND = "Unmatched"  # repair_listings.HOLDING_BRAND


def _group_key(category: str, title: str) -> Optional[Tuple[str, Optional[int]]]:
    key = chip_key(title, category)
    if key is None:
        return None
    vram = parse_vram(title) if category == "gpu" else None
    return key, vram


def _classify(envelopes, matcher) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], Set[Tuple[str, str]], List[str]]:
    """(untracked groups by (category, part_key), part keys now tracked, unrecognised titles)."""
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    tracked: Set[Tuple[str, str]] = set()
    unrecognised: List[str] = []
    for env in envelopes:
        category, retailer = env.get("category"), env.get("retailer")
        if category not in ("cpu", "gpu"):
            continue
        for item in env["items"]:
            title = (item.get("title") or "").strip()
            if not title or rules.is_excluded_title(title):
                continue
            kv = _group_key(category, title)
            if kv is None:
                unrecognised.append(title)
                continue
            key, vram = kv
            if rules.series_tier(category, key) is None:
                continue
            pkey = rules.part_key(category, key, vram)
            if matcher.resolve(title, category) is not None:
                tracked.add((category, pkey))
                continue
            g = groups.setdefault((category, pkey), {
                "key": key, "vram": vram, "titles": [], "retailers": set(), "count": 0,
                "min_price": None, "min_url": None,
            })
            g["count"] += 1
            g["retailers"].add(retailer)
            if len(g["titles"]) < SAMPLE_TITLES and title not in g["titles"]:
                g["titles"].append(title)
            price = item.get("price_aud")
            if price and (g["min_price"] is None or price < g["min_price"]):
                g["min_price"], g["min_url"] = price, item.get("url")
    return groups, tracked, unrecognised


def _placeholder_first_seen(conn: sqlite3.Connection) -> Dict[Tuple[str, str], str]:
    """Earliest snapshot date of each part already parked under 'Unmatched'."""
    rows = conn.execute(
        """SELECT p.category, l.variant_name, MIN(s.snapshot_date)
           FROM retailer_listings l
           JOIN products p ON p.id = l.product_id
           JOIN price_snapshots s ON s.retailer_listing_id = l.id
           WHERE p.brand = ?
           GROUP BY l.id""",
        (HOLDING_BRAND,),
    ).fetchall()
    out: Dict[Tuple[str, str], str] = {}
    for category, title, first in rows:
        kv = _group_key(category, title or "")
        if kv is None or first is None:
            continue
        pk = (category, rules.part_key(category, *kv))
        out[pk] = min(out.get(pk, first), first)
    return out


def _upsert(conn, groups, watchlist, today_iso: str) -> None:
    keys_with_vram_rows = {
        chip_key(wp["model"], wp["category"]) for wp in watchlist if wp["category"] == "gpu" and wp.get("vram_gb")
    }
    existing = {
        (r[0], r[1]) for r in conn.execute("SELECT category, part_key FROM discovered_parts")
    }
    first_seen = _placeholder_first_seen(conn) if any(k not in existing for k in groups) else {}
    for (category, pkey), g in groups.items():
        titles, key, vram = g["titles"], g["key"], g["vram"]
        fields = {
            "display_name": rules.display_name(category, key, vram, titles),
            "last_seen": today_iso,
            "listing_count": g["count"],
            "retailers": ",".join(sorted(g["retailers"])),
            "min_price": g["min_price"],
            "min_price_url": g["min_url"],
            "sample_titles": json.dumps(titles),
            "suggested_row": rules.suggested_row(category, key, vram, titles,
                                                 vram_in_model=key in keys_with_vram_rows),
        }
        if (category, pkey) in existing:
            sets = ", ".join(f"{k} = :{k}" for k in fields)
            conn.execute(f"UPDATE discovered_parts SET {sets} WHERE category = :c AND part_key = :p",
                         {**fields, "c": category, "p": pkey})
        else:
            conn.execute(
                """INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen,
                       listing_count, retailers, min_price, min_price_url, sample_titles, suggested_row)
                   VALUES (:c, :p, :display_name, 'untracked', :first, :last_seen, :listing_count, :retailers,
                       :min_price, :min_price_url, :sample_titles, :suggested_row)""",
                {**fields, "c": category, "p": pkey, "first": first_seen.get((category, pkey), today_iso)},
            )


def _flip_tracked(conn, tracked: Set[Tuple[str, str]]) -> None:
    for category, pkey in tracked:
        conn.execute(
            "UPDATE discovered_parts SET status = 'tracked' WHERE category = ? AND part_key = ?"
            " AND status IN ('untracked', 'requested')",
            (category, pkey),
        )


def find_conflicts(conn: sqlite3.Connection, today_iso: str) -> List[Tuple]:
    rows = conn.execute(
        """SELECT l.id, l.retailer, l.variant_name, p.id, p.category, p.model, p.vram_gb
           FROM retailer_listings l JOIN products p ON p.id = l.product_id
           WHERE l.status = 'active' AND p.tracked = 1 AND p.brand != ?""",
        (HOLDING_BRAND,),
    ).fetchall()
    out = []
    for lid, retailer, title, pid, category, model, vram_gb in rows:
        title = (title or "").strip()
        if not title:
            continue
        product_key = chip_key(model, category)
        title_key = chip_key(title, category)
        reason = None
        if rules.is_excluded_title(title):
            reason = "excluded item (bundle, laptop, workstation...) filed under a product"
        elif title_key is None:
            reason = "title names no recognisable chip"
        elif title_key != product_key:
            reason = f"title names {title_key}, product is {product_key}"
        elif category == "gpu" and vram_gb:
            v = parse_vram(title)
            if v and v != vram_gb:
                reason = f"title says {v}GB, product is {vram_gb}GB"
        if reason:
            out.append((lid, retailer, pid, title_key, reason, title, today_iso))
    return out


def notify_new(conn: sqlite3.Connection, today_iso: str) -> int:
    """Implemented in Task 6."""
    return 0


def run(
    db_path: Path = DB_PATH,
    data_dir: Path = DATA_DIR,
    today: Optional[date] = None,
    notify: bool = False,
    watchlist: Optional[list] = None,
) -> Dict[str, Any]:
    today = today or date.today()
    today_iso = today.isoformat()
    file_date = today.strftime(FILE_DATE_FORMAT)
    prune_catalogues(Path(data_dir), CATALOGUE_KEEP_DAYS, today)
    envelopes, bad = load_catalogues(Path(data_dir), file_date)
    present = {f"{e.get('retailer')}/{e.get('category')}" for e in envelopes}
    missing = [f"{r}/{c}" for r in ACTIVE_RETAILERS for c in ("cpu", "gpu") if f"{r}/{c}" not in present]
    missing += [f"unreadable: {name}" for name in bad]

    conn = sqlite3.connect(str(db_path))
    try:
        migrate_add_discovery_tables(conn)
        unrecognised: List[str] = []
        if envelopes:
            wl = watchlist if watchlist is not None else load_watchlist()
            groups, tracked, unrecognised = _classify(envelopes, Matcher(wl))
            _upsert(conn, groups, wl, today_iso)
            _flip_tracked(conn, tracked)
        conflicts = find_conflicts(conn, today_iso)
        conn.execute("DELETE FROM discovery_conflicts")
        conn.executemany("INSERT INTO discovery_conflicts VALUES (?, ?, ?, ?, ?, ?, ?)", conflicts)
        conn.execute(
            """INSERT INTO discovery_runs (run_date, finished_at, catalogue_files, missing,
                   unrecognised_count, unrecognised_samples) VALUES (?, ?, ?, ?, ?, ?)""",
            (today_iso, datetime.now().isoformat(timespec="seconds"), len(envelopes), json.dumps(missing),
             len(unrecognised), json.dumps(unrecognised[:UNRECOGNISED_SAMPLES])),
        )
        conn.execute(
            "DELETE FROM discovery_runs WHERE id NOT IN (SELECT id FROM discovery_runs ORDER BY id DESC LIMIT ?)",
            (RUNS_KEEP,),
        )
        conn.commit()
        untracked = conn.execute("SELECT COUNT(*) FROM discovered_parts WHERE status = 'untracked'").fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM discovered_parts WHERE status = 'untracked' AND first_seen = ?", (today_iso,)
        ).fetchone()[0]
        notified = notify_new(conn, today_iso) if notify else 0
    finally:
        conn.close()
    summary = {"catalogue_files": len(envelopes), "untracked": untracked, "new_today": new_today,
               "conflicts": len(conflicts), "missing": missing, "notified": notified}
    LOGGER.info("Discovery: %s", summary)
    return summary


if __name__ == "__main__":
    from config import setup_logging
    setup_logging()
    print(json.dumps(run(), indent=2))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest unit_testing/test_discover.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add discover.py unit_testing/test_discover.py
git commit -m "feat(discovery): classify catalogues, upsert parts, record conflicts and runs (#16)"
```

---

### Task 6: Discord notice, health check, `run_daily` wiring

**Files:**
- Modify: `discover.py` (`notify_new`), `health_checks.py` (new `check_discovery`), `run_daily.py` (step + `_db_checks` entry)
- Test: append to `unit_testing/test_discover.py` (reuses its `env` fixture), append to `unit_testing/test_health_checks.py`, append to `unit_testing/test_run_daily_resilience.py`

**Interfaces:**
- Consumes: `notify_discord.send_embed(webhook_url, embed) -> bool`, `notify_discord.load_dotenv()`, `run_daily.best_effort`, `run_daily.notify_enabled(args)`, `health_checks.CheckResult`
- Produces: `discover.notify_new(conn, today_iso) -> int` (parts sent), `discover.build_embed(rows: List[sqlite3.Row], base_url: str) -> dict`, `health_checks.check_discovery(db_path: Path, today: Optional[date] = None) -> List[CheckResult]`

- [ ] **Step 1: Write the failing tests**

```python
# appended to unit_testing/test_discover.py: Discovery Discord notice, new parts only, once (#16)

@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    monkeypatch.setattr("notify_discord.send_embed", lambda url, embed: calls.append(embed) or True)
    return calls


def test_new_parts_sent_once_with_details(env, sent):
    summary = _run(env, notify=True)
    assert summary["notified"] == 3
    embed = sent[0]
    assert embed["title"] == "New parts at retailers"
    assert "Radeon RX 9070 GRE 12GB" in embed["description"]
    assert "3 listings at pccg, scorptec, from $829" in embed["description"]


def test_second_run_same_day_sends_nothing(env, sent):
    _run(env, notify=True)
    _run(env, notify=True)
    assert len(sent) == 1


def test_ignored_parts_never_notify(env, sent):
    _run(env)  # notify off: rows created, notified_at NULL
    conn = sqlite3.connect(env[1])
    conn.execute("UPDATE discovered_parts SET status = 'ignored'")
    conn.commit()
    _run(env, notify=True)
    assert sent == []


def test_failed_send_retries_next_run(env, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    results = iter([False, True])
    calls = []
    monkeypatch.setattr("notify_discord.send_embed", lambda u, e: calls.append(e) or next(results))
    assert _run(env, notify=True)["notified"] == 0
    assert _run(env, notify=True)["notified"] == 3
    assert len(calls) == 2


def test_no_webhook_is_silent(env, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("notify_discord.load_dotenv", lambda *a, **k: None)
    called = []
    monkeypatch.setattr("notify_discord.send_embed", lambda *a: called.append(a) or True)
    assert _run(env, notify=True)["notified"] == 0
    assert called == []


def test_embed_caps_long_lists():
    rows = [{"display_name": f"Part {i}", "listing_count": 1, "retailers": "pccg", "min_price": 10.0}
            for i in range(40)]
    embed = discover.build_embed(rows, "http://dockerhost:3000")
    assert embed["url"] == "http://dockerhost:3000/discover"
    assert "and 15 more" in embed["description"]
    assert len(embed["description"]) < 4000
```

Append to `unit_testing/test_health_checks.py`:

```python
class TestCheckDiscovery:
    def _db(self, tmp_path):
        from ingest import init_db
        p = tmp_path / "h.db"
        init_db(p).close()
        return p

    def test_never_error_even_without_tables(self, tmp_path):
        import sqlite3
        from health_checks import CheckResult, check_discovery
        p = tmp_path / "bare.db"
        sqlite3.connect(p).close()
        assert all(r.status != CheckResult.ERROR for r in check_discovery(p))

    def test_warns_when_not_run_today(self, tmp_path):
        from datetime import date
        from health_checks import CheckResult, check_discovery
        [r] = check_discovery(self._db(tmp_path), today=date(2026, 10, 2))
        assert r.status == CheckResult.WARNING and "did not run" in r.message

    def test_warns_on_new_parts_and_conflicts(self, tmp_path):
        import sqlite3
        from datetime import date
        from health_checks import CheckResult, check_discovery
        p = self._db(tmp_path)
        conn = sqlite3.connect(p)
        conn.execute("INSERT INTO discovery_runs (run_date, finished_at, catalogue_files) VALUES ('2026-10-02','x',6)")
        conn.execute("INSERT INTO discovered_parts (category, part_key, display_name, first_seen, last_seen, suggested_row)"
                     " VALUES ('gpu','rtx 5050|8','GeForce RTX 5050 8GB','2026-10-02','2026-10-02','r')")
        conn.commit()
        [r] = check_discovery(p, today=date(2026, 10, 2))
        assert r.status == CheckResult.WARNING and "1 new part" in r.message and "GeForce RTX 5050 8GB" in r.message

    def test_ok_when_quiet(self, tmp_path):
        import sqlite3
        from datetime import date
        from health_checks import CheckResult, check_discovery
        p = self._db(tmp_path)
        conn = sqlite3.connect(p)
        conn.execute("INSERT INTO discovery_runs (run_date, finished_at, catalogue_files) VALUES ('2026-10-02','x',6)")
        conn.commit()
        [r] = check_discovery(p, today=date(2026, 10, 2))
        assert r.status == CheckResult.OK
```

Append to `unit_testing/test_run_daily_resilience.py` (reuse that file's existing helpers for building `args` and patching scrapers/ingest — read its first ~60 lines and follow the pattern exactly; the two assertions below are what matter):

```python
def test_discovery_crash_does_not_break_the_run(<existing fixtures>, monkeypatch):
    # Arrange a clean run with that file's helpers, then:
    import discover
    monkeypatch.setattr(discover, "run", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    # Act: run_daily.run(args)
    # Assert: the backup still ran and the exit code is the same as without discovery.


def test_check_discovery_is_registered():
    import run_daily
    assert "check_discovery" in [name for name, _ in run_daily._db_checks()]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_discover.py unit_testing/test_health_checks.py -q -k "notif or sent or embed or webhook or Discovery"`
Expected: FAIL — `notified == 0`, `AttributeError: build_embed`, `ImportError: check_discovery`

- [ ] **Step 3: Implement `notify_new` and `build_embed` in `discover.py`**

Replace the Task 5 stub with:

```python
EMBED_MAX_LINES = 25


def build_embed(rows, base_url: str) -> dict:
    lines = []
    for r in rows[:EMBED_MAX_LINES]:
        retailers = ", ".join(r["retailers"].split(",")) if r["retailers"] else "?"
        price = f"${r['min_price']:,.0f}" if r["min_price"] else "price unknown"
        plural = "listing" if r["listing_count"] == 1 else "listings"
        lines.append(f"**{r['display_name']}**: {r['listing_count']} {plural} at {retailers}, from {price}")
    if len(rows) > EMBED_MAX_LINES:
        lines.append(f"...and {len(rows) - EMBED_MAX_LINES} more on the Discover page")
    embed = {
        "title": "New parts at retailers",
        "description": "\n".join(lines) + "\n\nTrack or Ignore each one on the Discover page.",
        "color": 0x3B82F6,
    }
    if base_url:
        embed["url"] = f"{base_url.rstrip('/')}/discover"
    return embed


def notify_new(conn: sqlite3.Connection, today_iso: str) -> int:
    """Send untracked parts never notified before; stamp them only on success."""
    import os
    import notify_discord

    notify_discord.load_dotenv()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        return 0
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, display_name, listing_count, retailers, min_price FROM discovered_parts"
        " WHERE status = 'untracked' AND notified_at IS NULL ORDER BY first_seen DESC, display_name"
    ).fetchall()
    conn.row_factory = None
    if not rows:
        return 0
    base_url = os.environ.get("TRACKAROO_PUBLIC_BASE_URL", "")
    if not notify_discord.send_embed(webhook, build_embed(rows, base_url)):
        LOGGER.warning("Discovery notice not delivered; it will be retried on the next run")
        return 0
    stamp = datetime.now().isoformat(timespec="seconds")
    conn.executemany("UPDATE discovered_parts SET notified_at = ? WHERE id = ?", [(stamp, r["id"]) for r in rows])
    conn.commit()
    return len(rows)
```

- [ ] **Step 4: Implement `check_discovery` in `health_checks.py`**

Add near `check_backups`:

```python
def check_discovery(db_path: Path, today: Optional[date] = None) -> list[CheckResult]:
    """Discovery report (#16): WARNING on new parts, conflicts or a missed run. Never ERROR."""
    today_iso = (today or date.today()).isoformat()
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            ran = conn.execute("SELECT 1 FROM discovery_runs WHERE run_date = ? LIMIT 1", (today_iso,)).fetchone()
            new = [r[0] for r in conn.execute(
                "SELECT display_name FROM discovered_parts WHERE status = 'untracked' AND first_seen = ?"
                " ORDER BY display_name", (today_iso,))]
            conflicts = conn.execute("SELECT COUNT(*) FROM discovery_conflicts").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        return [CheckResult("discovery", CheckResult.WARNING, f"Discovery state unreadable: {e}")]
    problems = []
    if not ran:
        problems.append("Discovery did not run today")
    if new:
        problems.append(f"{len(new)} new part(s) at retailers: {', '.join(new[:5])}")
    if conflicts:
        problems.append(f"{conflicts} listing(s) filed under the wrong product (see /discover)")
    if problems:
        return [CheckResult("discovery", CheckResult.WARNING, "; ".join(problems))]
    return [CheckResult("discovery", CheckResult.OK, "No new parts or conflicts")]
```

Ensure `sqlite3` and `date` are imported in `health_checks.py` (add to the existing imports if missing).

- [ ] **Step 5: Wire into `run_daily.py`**

Import `check_discovery` alongside the other health-check imports. Add to `_db_checks()` (before `check_backups`):

```python
        ("check_discovery", lambda: check_discovery(DB_PATH)),
```

After the JSON-mirror `try/except` block and **before** `# ── Health check: validate DB state after ingestion`:

```python
        # ── Discovery report (#16) ──────────────────────────────────────
        # Untracked parts at retailers. Best-effort; its Discord notice is not
        # gated on the health result (a scrape problem does not make a new
        # part less real), only on notifications being enabled for this run.
        if not args.dry_run:
            def _run_discovery() -> Any:
                import discover
                return discover.run(notify=notify_enabled(args))

            best_effort("Discovery", _run_discovery)
```

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest unit_testing/test_discover.py unit_testing/test_health_checks.py unit_testing/test_run_daily.py unit_testing/test_run_daily_resilience.py unit_testing/test_retry.py -q`
Expected: all pass. If an existing test asserts the exact list or count of `_db_checks()`, add `check_discovery` to it.

- [ ] **Step 7: Commit**

```bash
git add discover.py health_checks.py run_daily.py unit_testing/test_discover.py unit_testing/test_health_checks.py unit_testing/test_run_daily_resilience.py
git commit -m "feat(discovery): Discord notice for new parts, check_discovery, run_daily step (#16)"
```

---

### Task 7: Web data layer

**Files:**
- Modify: `web/src/lib/types.ts`
- Create: `web/src/lib/server/discover.ts`
- Test: `web/test/discover.test.ts`

**Interfaces:**
- Consumes: tables from Task 3 (seeded by `test/helpers/seed.ts` via `db/schema.sql`)
- Produces (TypeScript):

```ts
export type DiscoveredStatus = 'untracked' | 'ignored' | 'requested' | 'tracked';
export type DiscoverAction = 'ignore' | 'unignore' | 'track' | 'untrack';
export interface DiscoveredPart {
	id: number; category: Category; partKey: string; displayName: string; status: DiscoveredStatus;
	firstSeen: string; lastSeen: string; listingCount: number; retailers: string[];
	minPrice: number | null; minPriceUrl: string | null; sampleTitles: string[]; suggestedRow: string;
}
export interface DiscoveryConflict {
	listingId: number; retailer: string; filedProductId: number; filedModel: string;
	titleKey: string | null; reason: string; title: string;
}
export interface DiscoveryRun {
	runDate: string; finishedAt: string; catalogueFiles: number; missing: string[];
	unrecognisedCount: number; unrecognisedSamples: string[];
}
export interface DiscoverPageData {
	lastRun: DiscoveryRun | null; isStale: boolean; today: string; newThisWeek: number;
	untracked: DiscoveredPart[]; requested: DiscoveredPart[]; ignored: DiscoveredPart[];
	conflicts: DiscoveryConflict[];
}
// server/discover.ts
export function localIsoDate(d?: Date): string;
export function getDiscoverPage(db: DB, today: string): DiscoverPageData;
export function getDiscoverPendingCount(db: DB): number;
export function applyDiscoverAction(db: DB, id: number, action: DiscoverAction, nowIso: string): 'ok' | 'not-found' | 'invalid';
export function isDiscoverAction(value: unknown): value is DiscoverAction;
```

- [ ] **Step 1: Write the failing tests**

```ts
// web/test/discover.test.ts
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import { createSeededDb, type SeededDb } from './helpers/seed';
import {
	applyDiscoverAction,
	getDiscoverPage,
	getDiscoverPendingCount,
	isDiscoverAction,
	localIsoDate
} from '../src/lib/server/discover';

let seeded: SeededDb;

function insertPart(db: any, key: string, status: string, firstSeen: string, extra: Record<string, unknown> = {}) {
	return Number(
		db
			.prepare(
				`INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen,
				   listing_count, retailers, min_price, min_price_url, sample_titles, suggested_row)
				 VALUES (@category, @key, @name, @status, @firstSeen, @lastSeen, 3, 'pccg,scorptec', 389, 'https://x',
				   '["A title"]', 'gpu,NVIDIA,GeForce RTX 5050,8GB,current,"rtx 5050"')`
			)
			.run({ category: 'gpu', key, name: `Part ${key}`, status, firstSeen, lastSeen: firstSeen, ...extra })
			.lastInsertRowid
	);
}

beforeAll(() => {
	seeded = createSeededDb();
});
afterAll(() => seeded.close());
beforeEach(() => {
	seeded.db.exec('DELETE FROM discovered_parts; DELETE FROM discovery_conflicts; DELETE FROM discovery_runs;');
});

describe('getDiscoverPage', () => {
	it('splits parts by status, newest first, and counts new this week', () => {
		insertPart(seeded.db, 'rtx 5050|8', 'untracked', '2026-10-02');
		insertPart(seeded.db, 'ryzen 5600gt', 'untracked', '2026-08-09');
		insertPart(seeded.db, 'ultra 270k plus', 'requested', '2026-10-01');
		insertPart(seeded.db, 'rx 7600 xt|16', 'ignored', '2026-09-20');
		insertPart(seeded.db, 'rtx 5060|8', 'tracked', '2026-09-01');
		const page = getDiscoverPage(seeded.db, '2026-10-02');
		expect(page.untracked.map((p) => p.partKey)).toEqual(['rtx 5050|8', 'ryzen 5600gt']);
		expect(page.requested.map((p) => p.partKey)).toEqual(['ultra 270k plus']);
		expect(page.ignored.map((p) => p.partKey)).toEqual(['rx 7600 xt|16']);
		expect(page.newThisWeek).toBe(1);
		expect(page.untracked[0].retailers).toEqual(['pccg', 'scorptec']);
		expect(page.untracked[0].sampleTitles).toEqual(['A title']);
	});

	it('is stale without a run today, fresh with one', () => {
		expect(getDiscoverPage(seeded.db, '2026-10-02').isStale).toBe(true);
		seeded.db
			.prepare(
				`INSERT INTO discovery_runs (run_date, finished_at, catalogue_files, missing) VALUES ('2026-10-02', '2026-10-02T04:41:00', 5, '["umart/gpu"]')`
			)
			.run();
		const page = getDiscoverPage(seeded.db, '2026-10-02');
		expect(page.isStale).toBe(false);
		expect(page.lastRun?.missing).toEqual(['umart/gpu']);
	});

	it('returns conflicts with the filed product model', () => {
		const listing = seeded.db
			.prepare('SELECT l.id, l.product_id, p.model FROM retailer_listings l JOIN products p ON p.id = l.product_id LIMIT 1')
			.get() as { id: number; product_id: number; model: string };
		seeded.db
			.prepare(
				`INSERT INTO discovery_conflicts VALUES (?, 'scorptec', ?, 'rx 9070 gre', 'title names rx 9070 gre, product is rx 9070', 'Sapphire RX 9070 GRE', '2026-10-02')`
			)
			.run(listing.id, listing.product_id);
		const [c] = getDiscoverPage(seeded.db, '2026-10-02').conflicts;
		expect(c.filedModel).toBe(listing.model);
		expect(c.reason).toContain('rx 9070 gre');
	});

	it('returns empty data when the tables do not exist (old DB)', () => {
		const bare = new Database(':memory:');
		const page = getDiscoverPage(bare, '2026-10-02');
		expect(page.untracked).toEqual([]);
		expect(page.lastRun).toBeNull();
		expect(getDiscoverPendingCount(bare)).toBe(0);
	});
});

describe('applyDiscoverAction', () => {
	it('follows the allowed transitions', () => {
		const id = insertPart(seeded.db, 'rtx 5050|8', 'untracked', '2026-10-02');
		expect(applyDiscoverAction(seeded.db, id, 'track', '2026-10-02T10:00:00')).toBe('ok');
		expect(applyDiscoverAction(seeded.db, id, 'track', '2026-10-02T10:00:00')).toBe('invalid');
		expect(applyDiscoverAction(seeded.db, id, 'untrack', '2026-10-02T10:01:00')).toBe('ok');
		expect(applyDiscoverAction(seeded.db, id, 'ignore', '2026-10-02T10:02:00')).toBe('ok');
		expect(applyDiscoverAction(seeded.db, id, 'unignore', '2026-10-02T10:03:00')).toBe('ok');
		const row = seeded.db.prepare('SELECT status, decided_at FROM discovered_parts WHERE id = ?').get(id) as any;
		expect(row).toEqual({ status: 'untracked', decided_at: '2026-10-02T10:03:00' });
	});

	it('refuses tracked parts and unknown ids', () => {
		const id = insertPart(seeded.db, 'rtx 5060|8', 'tracked', '2026-09-01');
		expect(applyDiscoverAction(seeded.db, id, 'ignore', 'x')).toBe('invalid');
		expect(applyDiscoverAction(seeded.db, 999999, 'ignore', 'x')).toBe('not-found');
	});

	it('pending count is untracked only', () => {
		insertPart(seeded.db, 'a', 'untracked', '2026-10-02');
		insertPart(seeded.db, 'b', 'requested', '2026-10-02');
		expect(getDiscoverPendingCount(seeded.db)).toBe(1);
	});
});

describe('helpers', () => {
	it('validates actions', () => {
		expect(isDiscoverAction('ignore')).toBe(true);
		expect(isDiscoverAction('delete')).toBe(false);
	});
	it('formats a local date', () => {
		expect(localIsoDate(new Date(2026, 9, 2, 23, 30))).toBe('2026-10-02');
	});
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `web/`): `npx vitest run test/discover.test.ts`
Expected: FAIL — cannot resolve `../src/lib/server/discover`

- [ ] **Step 3: Implement**

Add the types from the Interfaces block to `web/src/lib/types.ts` (with `Category` already defined there).

```ts
// web/src/lib/server/discover.ts
// Discovery report (#16): reads discovered_parts / discovery_conflicts /
// discovery_runs (written by discover.py) and records Track/Ignore decisions.
// Every reader tolerates a DB that predates the tables (returns empty data),
// so an old DB can never 500 the page or the nav badge.
import type { DB } from './db';
import type {
	DiscoverAction,
	DiscoverPageData,
	DiscoveredPart,
	DiscoveredStatus,
	DiscoveryConflict,
	DiscoveryRun
} from '$lib/types';

const ACTIONS: Record<DiscoverAction, { from: DiscoveredStatus[]; to: DiscoveredStatus }> = {
	ignore: { from: ['untracked', 'requested'], to: 'ignored' },
	unignore: { from: ['ignored'], to: 'untracked' },
	track: { from: ['untracked'], to: 'requested' },
	untrack: { from: ['requested'], to: 'untracked' }
};

export function isDiscoverAction(value: unknown): value is DiscoverAction {
	return typeof value === 'string' && value in ACTIONS;
}

export function localIsoDate(d: Date = new Date()): string {
	const pad = (n: number) => String(n).padStart(2, '0');
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function hasTables(db: DB): boolean {
	const row = db
		.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name IN ('discovered_parts', 'discovery_conflicts', 'discovery_runs')")
		.get() as { n: number };
	return row.n === 3;
}

function parseList(text: string | null): string[] {
	try {
		const v = JSON.parse(text ?? '[]');
		return Array.isArray(v) ? v.map(String) : [];
	} catch {
		return [];
	}
}

interface PartRow {
	id: number; category: 'cpu' | 'gpu'; part_key: string; display_name: string; status: DiscoveredStatus;
	first_seen: string; last_seen: string; listing_count: number; retailers: string; min_price: number | null;
	min_price_url: string | null; sample_titles: string; suggested_row: string;
}

function toPart(r: PartRow): DiscoveredPart {
	return {
		id: r.id, category: r.category, partKey: r.part_key, displayName: r.display_name, status: r.status,
		firstSeen: r.first_seen, lastSeen: r.last_seen, listingCount: r.listing_count,
		retailers: r.retailers ? r.retailers.split(',') : [], minPrice: r.min_price, minPriceUrl: r.min_price_url,
		sampleTitles: parseList(r.sample_titles), suggestedRow: r.suggested_row
	};
}

function daysBefore(iso: string, days: number): string {
	const [y, m, d] = iso.split('-').map(Number);
	return localIsoDate(new Date(y, m - 1, d - days));
}

export function getDiscoverPage(db: DB, today: string): DiscoverPageData {
	const empty: DiscoverPageData = {
		lastRun: null, isStale: true, today, newThisWeek: 0, untracked: [], requested: [], ignored: [], conflicts: []
	};
	if (!hasTables(db)) return empty;
	const parts = (
		db.prepare('SELECT * FROM discovered_parts ORDER BY first_seen DESC, display_name').all() as PartRow[]
	).map(toPart);
	const run = db.prepare('SELECT * FROM discovery_runs ORDER BY id DESC LIMIT 1').get() as
		| { run_date: string; finished_at: string; catalogue_files: number; missing: string; unrecognised_count: number; unrecognised_samples: string }
		| undefined;
	const lastRun: DiscoveryRun | null = run
		? {
				runDate: run.run_date, finishedAt: run.finished_at, catalogueFiles: run.catalogue_files,
				missing: parseList(run.missing), unrecognisedCount: run.unrecognised_count,
				unrecognisedSamples: parseList(run.unrecognised_samples)
			}
		: null;
	const conflicts = (
		db
			.prepare(
				`SELECT c.listing_id, c.retailer, c.filed_product_id, p.model AS filed_model, c.title_key, c.reason, c.title
				 FROM discovery_conflicts c JOIN products p ON p.id = c.filed_product_id ORDER BY p.model, c.title`
			)
			.all() as Array<{ listing_id: number; retailer: string; filed_product_id: number; filed_model: string; title_key: string | null; reason: string; title: string }>
	).map(
		(c): DiscoveryConflict => ({
			listingId: c.listing_id, retailer: c.retailer, filedProductId: c.filed_product_id, filedModel: c.filed_model,
			titleKey: c.title_key, reason: c.reason, title: c.title
		})
	);
	const untracked = parts.filter((p) => p.status === 'untracked');
	const weekStart = daysBefore(today, 6);
	return {
		lastRun,
		isStale: !lastRun || lastRun.runDate !== today,
		today,
		newThisWeek: untracked.filter((p) => p.firstSeen >= weekStart).length,
		untracked,
		requested: parts.filter((p) => p.status === 'requested'),
		ignored: parts.filter((p) => p.status === 'ignored'),
		conflicts
	};
}

export function getDiscoverPendingCount(db: DB): number {
	try {
		if (!hasTables(db)) return 0;
		return (db.prepare("SELECT COUNT(*) AS n FROM discovered_parts WHERE status = 'untracked'").get() as { n: number }).n;
	} catch {
		return 0;
	}
}

export function applyDiscoverAction(db: DB, id: number, action: DiscoverAction, nowIso: string): 'ok' | 'not-found' | 'invalid' {
	const row = db.prepare('SELECT status FROM discovered_parts WHERE id = ?').get(id) as { status: DiscoveredStatus } | undefined;
	if (!row) return 'not-found';
	const rule = ACTIONS[action];
	if (!rule.from.includes(row.status)) return 'invalid';
	db.prepare('UPDATE discovered_parts SET status = ?, decided_at = ? WHERE id = ?').run(rule.to, nowIso, id);
	return 'ok';
}
```

- [ ] **Step 4: Run to verify pass**

Run (from `web/`): `npx vitest run test/discover.test.ts && npm run check`
Expected: all pass; svelte-check 0 errors 0 warnings

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/server/discover.ts web/test/discover.test.ts
git commit -m "feat(web): discovery data layer and Track/Ignore transitions (#16)"
```

---

### Task 8: /discover page, nav badge, e2e

**Files:**
- Create: `web/src/routes/discover/+page.server.ts`, `web/src/routes/discover/+page.svelte`
- Modify: `web/src/lib/nav.ts`, `web/test/nav.test.ts`, `web/src/routes/+layout.server.ts`, `web/src/lib/components/Header.svelte`, `web/e2e/seed.mjs`, `web/e2e/app.spec.ts`, `web/e2e/mobile.spec.ts`

**Interfaces:**
- Consumes: Task 7 functions; `PageHead` component (read `web/src/lib/components/PageHead.svelte` for its props and use it the way `/deals/+page.svelte` does); `getDb`/`getWriteDb`
- Produces: route `/discover` with form actions `?/ignore`, `?/unignore`, `?/track`, `?/untrack` (field `id`); layout data `discoverPending: number`

- [ ] **Step 1: Write the failing tests**

`web/test/nav.test.ts`: change the expected labels to:

```ts
		expect(NAV_LINKS.map((l) => l.label)).toEqual(['Deals', 'GPUs', 'CPUs', 'Movers', 'Compare', 'Discover']);
```

`web/e2e/seed.mjs`: after the DB is fully built (just before it is closed), add:

```js
// ── Discovery fixtures (#16) ─────────────────────────────────────────
// Deterministic rows so /discover renders in e2e regardless of data/.
const today = (() => {
	const d = new Date();
	const p = (n) => String(n).padStart(2, '0');
	return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
})();
const part = db.prepare(
	`INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen, listing_count,
	   retailers, min_price, min_price_url, sample_titles, suggested_row)
	 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
);
part.run('gpu', 'rtx 5050|8', 'GeForce RTX 5050 8GB', 'untracked', today, today, 6, 'pccg,scorptec,umart', 389,
	'https://example.com/5050', JSON.stringify(['MSI GeForce RTX 5050 Ventus 2X OC 8G']),
	'gpu,NVIDIA,GeForce RTX 5050,8GB,current,"geforce rtx 5050|rtx 5050"');
part.run('cpu', 'ryzen 5600gt', 'Ryzen 5 5600GT', 'untracked', '2026-08-09', today, 4, 'pccg,scorptec', 189,
	'https://example.com/5600gt', JSON.stringify(['AMD Ryzen 5 5600GT Processor']),
	'cpu,AMD,Ryzen 5 5600GT,?c,current-2,"ryzen 5 5600gt|ryzen 5600gt"');
part.run('cpu', 'ultra 270k plus', 'Core Ultra 7 270K Plus', 'requested', today, today, 2, 'umart', 649,
	'https://example.com/270k', JSON.stringify(['Intel Core Ultra 7 270K Plus']),
	'cpu,Intel,Core Ultra 7 270K Plus,?c,current,"core ultra 7 270k plus|ultra 270k plus"');
part.run('gpu', 'rx 7600 xt|16', 'Radeon RX 7600 XT 16GB', 'ignored', '2026-09-20', today, 3, 'pccg', 499,
	'https://example.com/7600xt', JSON.stringify(['ASUS Dual RX 7600 XT 16GB']),
	'gpu,AMD,Radeon RX 7600 XT,16GB,current-1,"radeon rx 7600 xt|rx 7600 xt"');
db.prepare(
	`INSERT INTO discovery_runs (run_date, finished_at, catalogue_files, missing, unrecognised_count, unrecognised_samples)
	 VALUES (?, ?, 6, '[]', 1, ?)`
).run(today, `${today}T04:41:00`, JSON.stringify(['Arctic MX-6 thermal paste']));
const anyListing = db.prepare('SELECT id, product_id FROM retailer_listings LIMIT 1').get();
if (anyListing) {
	db.prepare(`INSERT INTO discovery_conflicts VALUES (?, 'scorptec', ?, 'rx 9070 gre', ?, ?, ?)`).run(
		anyListing.id, anyListing.product_id, 'title names rx 9070 gre, product is rx 9070',
		'Sapphire Pulse RX 9070 GRE 12GB', today
	);
}
```

(Use the seed file's actual DB variable name in place of `db` if it differs.)

Append to `web/e2e/app.spec.ts` (inside the file, using its `goto` helper):

```ts
test.describe.serial('/discover (#16)', () => {
	test('lists untracked, requested and conflicts; nav shows a badge', async ({ page }) => {
		await goto(page, '/discover');
		await expect(page.getByRole('heading', { level: 1 })).toHaveText('Discover');
		const untracked = page.getByTestId('discover-untracked');
		await expect(untracked.getByText('GeForce RTX 5050 8GB')).toBeVisible();
		await expect(untracked.getByText('Ryzen 5 5600GT')).toBeVisible();
		await expect(untracked.getByText('NEW')).toHaveCount(1);
		await expect(page.getByTestId('discover-requested').getByText('Core Ultra 7 270K Plus')).toBeVisible();
		await expect(page.getByTestId('discover-conflicts').getByText('Sapphire Pulse RX 9070 GRE 12GB')).toBeVisible();
		await expect(page.getByTestId('nav-discover-badge')).toHaveText('2');
	});

	test('Ignore hides a part; Un-ignore brings it back', async ({ page }) => {
		await goto(page, '/discover');
		const row = page.getByTestId('discover-untracked').locator('li', { hasText: 'Ryzen 5 5600GT' });
		await row.getByRole('button', { name: 'Ignore' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('discover-untracked').getByText('Ryzen 5 5600GT')).toHaveCount(0);
		await page.getByText(/Ignored \(\d+\)/).click();
		const ignored = page.getByTestId('discover-ignored').locator('li', { hasText: 'Ryzen 5 5600GT' });
		await ignored.getByRole('button', { name: 'Un-ignore' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('discover-untracked').getByText('Ryzen 5 5600GT')).toBeVisible();
	});

	test('Track moves a part to Requested with its watchlist row; Untrack reverts', async ({ page }) => {
		await goto(page, '/discover');
		const row = page.getByTestId('discover-untracked').locator('li', { hasText: 'GeForce RTX 5050 8GB' });
		await row.getByRole('button', { name: 'Track' }).click();
		await page.waitForLoadState('networkidle');
		const requested = page.getByTestId('discover-requested');
		await expect(requested.getByText('gpu,NVIDIA,GeForce RTX 5050,8GB,current')).toBeVisible();
		await requested.locator('li', { hasText: 'GeForce RTX 5050 8GB' }).getByRole('button', { name: 'Undo' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('discover-untracked').getByText('GeForce RTX 5050 8GB')).toBeVisible();
	});
});
```

Append to `web/e2e/mobile.spec.ts`, following its existing 390 px pattern (read the file and reuse its viewport setup and its overflow assertion helper):

```ts
test('/discover fits a 390px screen without horizontal scroll', async ({ page }) => {
	// <reuse the file's viewport + navigation helper>
	// await goto(page, '/discover');
	// <reuse the file's no-horizontal-overflow assertion>
	await expect(page.getByTestId('discover-untracked').getByRole('button', { name: 'Track' }).first()).toBeVisible();
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `web/`): `npx vitest run test/nav.test.ts` → FAIL (no Discover link). `npm run test:e2e -- -g discover` → FAIL (404 on /discover).

- [ ] **Step 3: Server route**

```ts
// web/src/routes/discover/+page.server.ts
import { fail, redirect } from '@sveltejs/kit';
import { getDb, getWriteDb } from '$lib/server/db';
import { applyDiscoverAction, getDiscoverPage, isDiscoverAction, localIsoDate } from '$lib/server/discover';
import type { DiscoverAction } from '$lib/types';

// Not memoised: a Track/Ignore click must show on the redirect straight back.
export function load() {
	return getDiscoverPage(getDb(), localIsoDate());
}

async function act(request: Request, action: DiscoverAction) {
	const form = await request.formData();
	const id = Number(form.get('id'));
	if (!Number.isInteger(id) || id <= 0 || !isDiscoverAction(action)) {
		return fail(400, { error: 'Unknown part.' });
	}
	const now = new Date();
	const result = applyDiscoverAction(getWriteDb(), id, action, `${localIsoDate(now)}T${now.toTimeString().slice(0, 8)}`);
	if (result === 'not-found') return fail(404, { error: 'That part no longer exists.' });
	if (result === 'invalid') return fail(400, { error: 'That change is not possible from its current state.' });
	redirect(303, '/discover');
}

export const actions = {
	ignore: ({ request }) => act(request, 'ignore'),
	unignore: ({ request }) => act(request, 'unignore'),
	track: ({ request }) => act(request, 'track'),
	untrack: ({ request }) => act(request, 'untrack')
};
```

- [ ] **Step 4: Page**

```svelte
<!-- web/src/routes/discover/+page.svelte -->
<script lang="ts">
	import PageHead from '$lib/components/PageHead.svelte';
	import type { DiscoveredPart } from '$lib/types';

	let { data, form } = $props();

	const RETAILER_LABEL: Record<string, string> = { pccg: 'PCCG', scorptec: 'Scorptec', umart: 'Umart' };
	const label = (r: string) => RETAILER_LABEL[r] ?? r;
	const day = (iso: string) =>
		new Date(`${iso}T00:00:00`).toLocaleDateString('en-AU', { day: 'numeric', month: 'short' });
	const money = (n: number | null) => (n == null ? '–' : `$${Math.round(n).toLocaleString('en-AU')}`);
	const isNew = (p: DiscoveredPart) => {
		const [y, m, d] = data.today.split('-').map(Number);
		const weekAgo = new Date(y, m - 1, d - 6);
		return new Date(`${p.firstSeen}T00:00:00`) >= weekAgo;
	};
	const ranAt = $derived(data.lastRun ? data.lastRun.finishedAt.slice(11, 16) : null);
	let copied = $state<number | null>(null);
	async function copy(p: DiscoveredPart) {
		try {
			await navigator.clipboard.writeText(p.suggestedRow);
			copied = p.id;
		} catch {
			copied = null;
		}
	}
</script>

<PageHead title="Discover" description="Parts retailers sell that Trackaroo does not track yet." />

<div class="mx-auto max-w-5xl space-y-8 px-4 py-6">
	<header class="space-y-2">
		<h1 class="text-xl font-semibold text-text">Discover</h1>
		<p class="text-sm text-text-muted">
			{data.newThisWeek} new this week · {data.untracked.length} untracked · {data.conflicts.length} conflicts
			{#if data.lastRun} · last checked {day(data.lastRun.runDate)} {ranAt}{/if}
		</p>
		{#if data.isStale}
			<p class="rounded-md bg-warning-soft px-3 py-2 text-sm text-text" role="status">
				{data.lastRun ? `Showing results from ${day(data.lastRun.runDate)}: discovery has not run today yet.` : 'Discovery has not run yet.'}
			</p>
		{/if}
		{#if data.lastRun?.missing.length}
			<p class="text-xs text-text-muted">Missing today: {data.lastRun.missing.join(', ')}</p>
		{/if}
		{#if form?.error}<p class="text-sm text-danger" role="alert">{form.error}</p>{/if}
	</header>

	<section aria-labelledby="untracked-h">
		<h2 id="untracked-h" class="mb-2 text-sm font-semibold text-text">Untracked parts ({data.untracked.length})</h2>
		{#if data.untracked.length === 0}
			<p class="text-sm text-text-muted">Nothing untracked: every in-scope part on sale is tracked or ignored.</p>
		{:else}
			<ul data-testid="discover-untracked" class="divide-y divide-border rounded-md border border-border">
				{#each data.untracked as p (p.id)}
					<li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-3 {p.lastSeen < data.today ? 'opacity-60' : ''}">
						<details class="min-w-0 flex-1 basis-56">
							<summary class="cursor-pointer text-sm font-medium text-text">
								{p.displayName}
								{#if isNew(p)}<span class="ml-1 rounded bg-accent px-1.5 py-0.5 text-xs font-semibold text-on-accent">NEW</span>{/if}
							</summary>
							<ul class="mt-1 list-disc pl-5 text-xs text-text-muted">
								{#each p.sampleTitles as t}<li>{t}</li>{/each}
							</ul>
						</details>
						<span class="text-xs text-text-muted">
							first seen {day(p.firstSeen)}{#if p.lastSeen < data.today} · last seen {day(p.lastSeen)}{/if}
						</span>
						<span class="text-xs text-text-muted">{p.listingCount} listings · {p.retailers.map(label).join(', ')}</span>
						<span class="tabular-nums text-sm text-text">
							from {#if p.minPriceUrl}<a href={p.minPriceUrl} target="_blank" rel="noopener noreferrer">{money(p.minPrice)} ↗</a>{:else}{money(p.minPrice)}{/if}
						</span>
						<span class="flex gap-2">
							<form method="POST" action="?/track"><input type="hidden" name="id" value={p.id} /><button class="btn-primary min-h-6 px-3 text-sm">Track</button></form>
							<form method="POST" action="?/ignore"><input type="hidden" name="id" value={p.id} /><button class="btn-secondary min-h-6 px-3 text-sm">Ignore</button></form>
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section aria-labelledby="requested-h">
		<h2 id="requested-h" class="mb-2 text-sm font-semibold text-text">Requested ({data.requested.length})</h2>
		<p class="mb-2 text-xs text-text-muted">
			These rows get added to <code>db/watchlist.csv</code> in a PR; the part is tracked after the next
			<code>deploy/redeploy.sh</code>. See README, "Discovering and adding new parts".
		</p>
		<ul data-testid="discover-requested" class="space-y-2">
			{#each data.requested as p (p.id)}
				<li class="rounded-md border border-border px-3 py-2">
					<div class="flex flex-wrap items-center justify-between gap-2">
						<span class="text-sm font-medium text-text">{p.displayName}</span>
						<span class="flex gap-2">
							<button type="button" class="btn-secondary min-h-6 px-3 text-sm" onclick={() => copy(p)}>{copied === p.id ? 'Copied' : 'Copy row'}</button>
							<form method="POST" action="?/untrack"><input type="hidden" name="id" value={p.id} /><button class="btn-secondary min-h-6 px-3 text-sm">Undo</button></form>
						</span>
					</div>
					<code class="mt-1 block overflow-x-auto whitespace-pre text-xs text-text-muted">{p.suggestedRow}</code>
				</li>
			{/each}
		</ul>
	</section>

	<section aria-labelledby="conflicts-h">
		<h2 id="conflicts-h" class="mb-2 text-sm font-semibold text-text">Conflicts ({data.conflicts.length})</h2>
		{#if data.conflicts.length === 0}
			<p class="text-sm text-text-muted">None: every listing matches its product.</p>
		{:else}
			<ul data-testid="discover-conflicts" class="divide-y divide-border rounded-md border border-border">
				{#each data.conflicts as c (c.listingId)}
					<li class="px-3 py-2 text-sm">
						<span class="text-text">{c.title}</span>
						<span class="block text-xs text-text-muted">
							{label(c.retailer)} · filed under <a href="/product/{c.filedProductId}">{c.filedModel}</a> · {c.reason}
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<details>
		<summary class="cursor-pointer text-sm font-semibold text-text">Ignored ({data.ignored.length})</summary>
		<ul data-testid="discover-ignored" class="mt-2 divide-y divide-border rounded-md border border-border">
			{#each data.ignored as p (p.id)}
				<li class="flex items-center justify-between gap-2 px-3 py-2 text-sm">
					<span class="text-text">{p.displayName}</span>
					<form method="POST" action="?/unignore"><input type="hidden" name="id" value={p.id} /><button class="btn-secondary min-h-6 px-3 text-sm">Un-ignore</button></form>
				</li>
			{/each}
		</ul>
	</details>

	{#if data.lastRun?.unrecognisedCount}
		<details>
			<summary class="cursor-pointer text-sm font-semibold text-text">Unrecognised titles ({data.lastRun.unrecognisedCount})</summary>
			<p class="mt-1 text-xs text-text-muted">Items in the CPU/GPU categories that name no known chip. Usually accessories; only a concern if a real CPU or GPU shows up here.</p>
			<ul class="mt-2 list-disc pl-5 text-xs text-text-muted">
				{#each data.lastRun.unrecognisedSamples as t}<li>{t}</li>{/each}
			</ul>
		</details>
	{/if}
</div>
```

Before running, open `web/src/app.css` and replace any class above that does not exist there (`btn-primary`, `btn-secondary`, `bg-warning-soft`, `text-on-accent`, `text-danger`, `divide-border`) with the equivalents `/deals` and the price-alert form use. Do not invent new tokens.

- [ ] **Step 5: Nav + badge**

`web/src/lib/nav.ts`: append `{ href: '/discover', label: 'Discover' }` to `NAV_LINKS`.

`web/src/routes/+layout.server.ts`: import `getDiscoverPendingCount` from `$lib/server/discover` and add to the returned object (not memoised: it changes on a click):

```ts
		discoverPending: getDiscoverPendingCount(db),
```

`web/src/lib/components/Header.svelte`: inside the `{#each NAV_LINKS ...}` link markup, after the label text, add:

```svelte
{#if link.href === '/discover' && (page.data as { discoverPending?: number }).discoverPending}
	<span data-testid="nav-discover-badge" class="ml-1 rounded-full bg-accent px-1.5 text-xs font-semibold text-on-accent"
		aria-label="{(page.data as { discoverPending?: number }).discoverPending} parts waiting">{(page.data as { discoverPending?: number }).discoverPending}</span>
{/if}
```

- [ ] **Step 6: Run to verify pass**

Run (from `web/`): `npm run check && npm test && npm run test:e2e`
Expected: svelte-check 0/0; vitest all pass; Playwright all pass (including the new /discover and mobile tests)

- [ ] **Step 7: Commit**

```bash
git add web/src/routes/discover web/src/lib/nav.ts web/test/nav.test.ts web/src/routes/+layout.server.ts web/src/lib/components/Header.svelte web/e2e/seed.mjs web/e2e/app.spec.ts web/e2e/mobile.spec.ts
git commit -m "feat(web): /discover page with Track/Ignore, nav badge (#16)"
```

---

### Task 9: README guide and docs

**Files:**
- Modify: `README.md`, `docs/ARCHITECTURE.md` (Part 2 §7), `CLAUDE.md`, `STATUS.md`

- [ ] **Step 1: README — add a section "Discovering and adding new parts"** (place it after the section on running the pipeline; keep README's existing heading style). It must contain, with these exact worked examples:

1. **What it does** (3-4 sentences): scrapers keep a 30-day catalogue of everything they see in `data/catalogue/`; after each daily run, `discover.py` lists in-scope parts the watchlist does not track; new ones are posted once to the Discord digest channel as "New parts at retailers"; all of them are on **/discover**, where you Track or Ignore them.
2. **Example: adding the RTX 5050**, numbered:
   1. Discord shows: `GeForce RTX 5050 8GB: 6 listings at pccg, scorptec, umart, from $389`.
   2. Open `http://<server>:3000/discover`; the row shows first seen, listings, retailers, lowest price; click it to see real listing titles.
   3. Click **Track**. It moves to **Requested** with the row `gpu,NVIDIA,GeForce RTX 5050,8GB,current,"geforce rtx 5050|rtx 5050"`.
   4. Add that row to `db/watchlist.csv` in a branch and open a PR (or ask Claude to). For a CPU the row says `?c`, e.g. `cpu,AMD,Ryzen 5 5600GT,?c,current-2,...`: replace `?c` with the core count (`6c`) from the manufacturer's spec page.
   5. CI checks the row (`test_watchlist_validation.py`, `test_discover_rules.py`). Merge.
   6. On the server, outside 04:00-09:59 Melbourne: `cd ~/docker/Trackaroo && deploy/redeploy.sh`.
   7. Next daily run: the part leaves Requested (status `tracked`) and appears under GPUs with prices from that day. Specs arrive on the Sunday spec sync, or run `docker compose exec trackaroo python sync_specs.py --category gpu`.
3. **Example: ignoring the Ryzen 5 5600GT**: click **Ignore**; it is hidden and never notifies again. To undo: open **Ignored** at the bottom of /discover and click **Un-ignore**.
4. **Conflicts**: example line `Sapphire Pulse RX 9070 GRE 12GB · filed under Radeon RX 9070 · title names rx 9070 gre, product is rx 9070`. Meaning: a listing is filed under the wrong product. Fix: if the right product exists, run `repair_listings.py` (dry run, then `--apply`); if it does not, Track the part first. If titles look right but are flagged, it is a matcher bug: open an issue with the line.
5. **A new generation launches** (e.g. RTX 60): it appears on /discover as `current`. Update the scope table in `discover_rules.py` (`_GPU_TIERS` etc.) and `docs/ARCHITECTURE.md` Part 2 together, in one PR.
6. **Troubleshooting**: no Discord message (check `DISCORD_WEBHOOK_URL`; a part is announced once only, check /discover); "has not run today" banner (check `docker compose logs trackaroo | grep -i discovery`); a real CPU/GPU under "Unrecognised titles" (the chip-key patterns in `scraper/chip_key.py` need it; open an issue); catalogue files (`data/catalogue/`, kept 30 days, safe to delete, never ingested).
7. **Security note**: the buttons have no login, like price alerts; anyone who can open the dashboard can click them. Put the site behind a login before exposing it to the internet.

- [ ] **Step 2: ARCHITECTURE Part 2 §7**: add at the start of "Adding or removing a product": "Most additions start on **/discover** (README, 'Discovering and adding new parts'), which gives you the row." Add to the §7 removal text nothing.

- [ ] **Step 3: CLAUDE.md**: under "Data integrity", add:

```markdown
- **`data/catalogue/` is a report, not a backup** (#16). Scrapers write every
  item they see there via `scraper/catalogue_io.save_catalogue` (atomic, never
  through `save_snapshot`, kept 30 days). Never move these files to the top of
  `data/`: `ingest_today` globs `data/*_{date}.json` and the web seeders read
  every `data/*.json`.
```

and under "Pipeline conventions":

```markdown
- `discover.py` runs after ingest through `best_effort`; `check_discovery` is
  WARNING-only. The scope table in `discover_rules.py` must agree with
  ARCHITECTURE Part 2 and `db/watchlist.csv` (`test_discover_rules.py`).
```

Update the test counts in CLAUDE.md's Commands section to the measured numbers from Task 10.

- [ ] **Step 4: STATUS.md**: add a dated bullet at the top of Recent changes: what shipped, the branch, counts, and "not deployed".

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ARCHITECTURE.md CLAUDE.md STATUS.md
git commit -m "docs: discovering and adding new parts (#16)"
```

---

### Task 10: Full gate

- [ ] **Step 1:** From the repo root: `python -m pytest -q` → all pass (record the count).
- [ ] **Step 2:** From `web/`: `npm run check` (0 errors, 0 warnings), `npm test`, `npm run test:e2e` → all pass (record counts).
- [ ] **Step 3:** Offline image boot (never with mounts, never without `--network none`):

```bash
GIT_SHA=$(git rev-parse --short HEAD) docker compose build
docker run -d --name trackaroo-verify --network none -e SKIP_PIPELINE=1 trackaroo:latest
for i in $(seq 1 40); do s=$(docker inspect -f '{{.State.Health.Status}}' trackaroo-verify); [ "$s" = healthy ] && break; sleep 10; done; echo "$s"
docker exec trackaroo-verify node -e "fetch('http://127.0.0.1:3000/discover').then(r=>console.log(r.status))"
docker exec trackaroo-verify sh -c 'ls /app/seed-data | grep -c catalogue || true'
docker rm -f trackaroo-verify
```

Expected: `healthy`, `/discover` 200, `0` catalogue entries in `seed-data`.
- [ ] **Step 4:** Update the counts in CLAUDE.md/STATUS.md if they changed, commit `docs: test counts after discovery`.
- [ ] **Step 5:** Push the branch and open the PR (body: what it does, the README section, test counts, "not deployed; deploy with deploy/redeploy.sh outside 04:00-09:59"; then `gh pr checks` until green).
