# Generations, Retirement and Watchlist CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a generation launch (Zen 6, next GPUs) one config line plus new SKU rows, make retirement one reversible CSV value, and suggest retiring parts that vanished from every retailer.

**Architecture:** `db/generations.toml` is the single ordered list of series per product line; `db/watchlist.csv` rows carry `series` + `status`, and tier/tracked are derived (`db/generations.py`, `db/watchlist.py`). `seed.py` mirrors the toml into a `generations` table and syncs `tracked` both ways behind a bulk guard; the web reads tier labels from that table. A daily `retire_suggest.py` step fills `retire_suggestions`, shown on `/discover` and in Discord. `manage_watchlist.py` edits the CSV/toml (`rollover`, `add`, `retire`, `check`) and repairs listings (`reassign`).

**Tech Stack:** Python 3.12 (stdlib `tomllib`, sqlite3, argparse, difflib), pytest; SvelteKit 2 / Svelte 5, better-sqlite3, Vitest, Playwright; `smol-toml` (web devDependency, e2e seeding only).

**Spec:** `docs/superpowers/specs/2026-10-06-generations-retirement-design.md`

## Global Constraints

- Python 3.12; no new runtime Python dependencies (`tomllib` is stdlib). `requirements*.txt` untouched.
- **Never open `db/trackaroo.db`** (not even read-only). Tests use temp DBs (`tmp_path`) and temp CSV/toml files.
- Tests never touch the network (`unit_testing/conftest.py` blocks non-loopback sockets); mock Discord.
- No emojis anywhere (UI, logs, Discord, docs). Web icons only from `@lucide/svelte`.
- Every `web/src` `.ts`/`.svelte` file stays <= 350 lines (`web/test/boundaries.test.ts`); client code never imports `$lib/server`.
- Tier values stay exactly `current`, `current-1`, `current-2`; the `products.generation_tier` CHECK does not change.
- Never delete product or price data. Retirement = `tracked = 0`.
- Nothing untracks a product without the CSV changing (no automatic retirement).
- Bulk guard limit: `max(5, total_products // 10)` tracked flips per seed run.
- Stale threshold: `TRACKAROO_RETIRE_STALE_DAYS`, default `30`; Keep hides for `90` days.
- Labels in the toml are exactly today's `TIER_LINE_LABELS` strings (first deploy changes no visible text).
- Commits: conventional prefix, message via heredoc, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Each PR adds one line under `## Unreleased` in `CHANGELOG.md`.
- Full gate before each PR: `python -m pytest -q` (repo root); from `web/`: `npm run check` (0/0), `npm test`, `npm run test:e2e`.
- Use the Edit tool (not python heredoc string replacement) for multi-line edits to existing files.

## Review Focus

- **Boot after a rollover is deployed without `--allow-bulk`:** the container must still boot; seed writes nothing to `products`, logs an ERROR naming the flips, and the entrypoint continues (Task 4 test + entrypoint change).
- **First deploy onto prod's existing DB** (no `series` column, no `generations` table; seed runs *before* migrate at boot): seed must self-migrate and report 0 tracked flips (Task 4 test `test_first_seed_on_old_db_has_zero_flips`).
- **A product added before it is on sale** (pre-launch SKU) must not be flagged stale until it is 30 days old; never-listed old products ARE flagged (Task 9 tests).
- **The CSV saved with CRLF line endings** (Windows editor) must round-trip through the CLI without changing every line (Task 11 test `test_crlf_preserved`).
- **A stale Retire/Keep form** (row already gone or already requested) returns 400/404, never 500 (Task 10 test).

---

# Phase 1 — PR 1: data model and seed (#17, #18)

Branch: `feat/2026-10-06-generations` (already exists, holds the spec + this plan).

### Task 1: `db/generations.toml` + `db/generations.py`

**Files:**
- Create: `db/generations.toml`
- Create: `db/generations.py`
- Modify: `config.py` (add `GENERATIONS_PATH` next to `WATCHLIST_PATH`)
- Test: `unit_testing/test_generations.py`

**Interfaces:**
- Produces:
  - `config.GENERATIONS_PATH: Path` (= `DB_DIR / "generations.toml"`, same style as `WATCHLIST_PATH`)
  - `db.generations.TIERS = ("current", "current-1", "current-2")`
  - `class GenerationsError(ValueError)`
  - `@dataclass(frozen=True) Series(key: str, label: str, line_id: str, position: int, chips: tuple[str, ...])`
  - `@dataclass(frozen=True) Line(id: str, keep_all: bool, series: tuple[Series, ...])`
  - `@dataclass(frozen=True) Generations(lines: dict[str, Line], series: dict[str, Series])` with methods `in_scope(key) -> bool`, `tier(key) -> str | None`, `chip_series(family, gen) -> Series | None`, `chip_gens(family) -> list[str]`
  - `line_id(brand: str, category: str) -> str` (e.g. `("AMD", "cpu") -> "amd-cpu"`)
  - `parse_generations(text: str, source: str = "generations.toml") -> Generations`
  - `load_generations(path=GENERATIONS_PATH) -> Generations`
  - `default_generations() -> Generations` (lru_cached `load_generations()`)

- [ ] **Step 1: Create the config file**

`db/generations.toml`:

```toml
# Trackaroo product generations -- the ONE list of series per product line (#17).
#
# Series are newest first. Position decides the tier: 0 = current,
# 1 = current-1, 2 = current-2; position 3 or later is out of scope and every
# watchlist row in it is untracked by seed.py. keep_all = true keeps every
# series of a line in scope (Intel Arc).
#
# A launch: add the new series at the TOP of its line (or run
# `python manage_watchlist.py rollover ...`), add the SKU rows to
# db/watchlist.csv with that series key, then seed.py --allow-bulk.
#
# key    -- what db/watchlist.csv's `series` column refers to (unique in file)
# label  -- shown on the dashboard (group headers, breadcrumbs, filters)
# chips  -- "family:gen" tokens discovery uses to place an untracked part in a
#           series (discover_rules.py): rtx:5 = RTX 50xx, ryzen:9 = Ryzen 9xxx,
#           core:14 = Core i 14xxx, ultra:2 = Core Ultra 2xx, arc:b = Arc Bxxx

[[line]]
id = "amd-cpu"
series = [
  { key = "zen5", label = "Ryzen 9000 (Zen 5)", chips = ["ryzen:9"] },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)", chips = ["ryzen:7", "ryzen:8"] },
  { key = "zen3", label = "Ryzen 5000 (Zen 3)", chips = ["ryzen:5"] },
]

[[line]]
id = "intel-cpu"
series = [
  { key = "arrow-lake", label = "Core Ultra 200 (Arrow Lake)", chips = ["ultra:2"] },
  { key = "core-14", label = "Core 14th Gen", chips = ["core:14"] },
  { key = "core-13", label = "Core 13th Gen", chips = ["core:13"] },
]

[[line]]
id = "nvidia-gpu"
series = [
  { key = "rtx50", label = "RTX 50 (Blackwell)", chips = ["rtx:5"] },
  { key = "rtx40", label = "RTX 40 (Ada)", chips = ["rtx:4"] },
  { key = "rtx30", label = "RTX 30 (Ampere)", chips = ["rtx:3"] },
]

[[line]]
id = "amd-gpu"
series = [
  { key = "rx9000", label = "RX 9000 (RDNA 4)", chips = ["rx:9"] },
  { key = "rx7000", label = "RX 7000 (RDNA 3)", chips = ["rx:7"] },
  { key = "rx6000", label = "RX 6000 (RDNA 2)", chips = ["rx:6"] },
]

[[line]]
id = "intel-gpu"
keep_all = true
series = [
  { key = "arc-b", label = "Arc B (Battlemage)", chips = ["arc:b"] },
  { key = "arc-a", label = "Arc A (Alchemist)", chips = ["arc:a"] },
]
```

Add to `config.py` directly below `WATCHLIST_PATH`:

```python
GENERATIONS_PATH = WATCHLIST_PATH.parent / "generations.toml"
```

- [ ] **Step 2: Write the failing tests**

`unit_testing/test_generations.py`:

```python
"""db/generations.py: parsing, validation and tier derivation (#17)."""
import pytest

from db.generations import (
    TIERS, GenerationsError, default_generations, line_id, load_generations, parse_generations,
)

MINI = """
[[line]]
id = "amd-cpu"
series = [
  { key = "zen6", label = "Ryzen 10000 (Zen 6)", chips = ["ryzen:10"] },
  { key = "zen5", label = "Ryzen 9000 (Zen 5)", chips = ["ryzen:9"] },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)", chips = ["ryzen:7", "ryzen:8"] },
  { key = "zen3", label = "Ryzen 5000 (Zen 3)", chips = ["ryzen:5"] },
]

[[line]]
id = "intel-gpu"
keep_all = true
series = [
  { key = "arc-c", label = "Arc C", chips = ["arc:c"] },
  { key = "arc-b", label = "Arc B", chips = ["arc:b"] },
  { key = "arc-a", label = "Arc A", chips = ["arc:a"] },
  { key = "arc-x", label = "Arc X", chips = [] },
]
"""


def test_position_gives_tier():
    g = parse_generations(MINI)
    assert [g.tier(k) for k in ("zen6", "zen5", "zen4")] == list(TIERS)


def test_fourth_series_is_out_of_scope():
    g = parse_generations(MINI)
    assert g.tier("zen3") is None
    assert g.in_scope("zen3") is False


def test_keep_all_keeps_old_series_in_scope_at_current_2():
    g = parse_generations(MINI)
    assert g.in_scope("arc-x") is True
    assert g.tier("arc-x") == "current-2"


def test_chip_lookup():
    g = parse_generations(MINI)
    assert g.chip_series("ryzen", "8").key == "zen4"
    assert g.chip_series("ryzen", "3") is None
    assert sorted(g.chip_gens("ryzen")) == ["10", "5", "7", "8", "9"]


def test_line_id():
    assert line_id("AMD", "cpu") == "amd-cpu"
    assert line_id(" NVIDIA ", "GPU") == "nvidia-gpu"


@pytest.mark.parametrize("text, needle", [
    ("not = [valid", "not valid TOML"),
    ("", "no [[line]]"),
    ('[[line]]\nid = "amd-gpu-x"\nseries = [{ key = "a", label = "A" }]', "unknown line"),
    ('[[line]]\nid = "amd-cpu"\nseries = []', "has no series"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "Zen 5", label = "A" }]', "key"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "" }]', "label"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "A" }, { key = "a", label = "B" }]', "duplicate series key"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "A" }]\n[[line]]\nid = "amd-cpu"\nseries = [{ key = "b", label = "B" }]', "duplicate line"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "A", chips = ["ryzen9"] }]', "chip"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "A", chips = ["ryzen:9"] }, { key = "b", label = "B", chips = ["ryzen:9"] }]', "ryzen:9"),
    ('[[line]]\nid = "amd-cpu"\nkeep_all = "yes"\nseries = [{ key = "a", label = "A" }]', "keep_all"),
])
def test_invalid_config_is_rejected_with_a_named_reason(text, needle):
    with pytest.raises(GenerationsError, match=needle.replace("[", r"\[")):
        parse_generations(text)


def test_missing_file(tmp_path):
    with pytest.raises(GenerationsError, match="not found"):
        load_generations(tmp_path / "nope.toml")


def test_real_file_loads_and_matches_todays_labels():
    g = default_generations()
    assert set(g.lines) == {"amd-cpu", "intel-cpu", "nvidia-gpu", "amd-gpu", "intel-gpu"}
    assert g.series["rtx50"].label == "RTX 50 (Blackwell)"
    assert g.series["zen4"].chips == ("ryzen:7", "ryzen:8")
    assert g.lines["intel-gpu"].keep_all is True
    for line in g.lines.values():
        assert len(line.series) >= 2
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest unit_testing/test_generations.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'db.generations'`

- [ ] **Step 4: Implement `db/generations.py`**

```python
"""Product generations: the one ordered list of series per product line (#17).

db/generations.toml lists each line's series newest first. A series'
position is its tier (0 current, 1 current-1, 2 current-2); position 3 or
later is out of scope unless the line sets keep_all. db/watchlist.py derives
every row's tier and tracked flag from here, seed.py mirrors it into the
`generations` table the dashboard reads labels from, and discover_rules.py
uses the `chips` tokens to place untracked parts.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import GENERATIONS_PATH

TIERS = ("current", "current-1", "current-2")
KNOWN_LINES = ("amd-cpu", "intel-cpu", "nvidia-gpu", "amd-gpu", "intel-gpu")
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CHIP_RE = re.compile(r"^[a-z]+:[a-z0-9]+$")


class GenerationsError(ValueError):
    """db/generations.toml is unusable. The message names the line/series to fix."""


@dataclass(frozen=True)
class Series:
    key: str
    label: str
    line_id: str
    position: int
    chips: Tuple[str, ...]


@dataclass(frozen=True)
class Line:
    id: str
    keep_all: bool
    series: Tuple[Series, ...]


@dataclass(frozen=True)
class Generations:
    lines: Dict[str, Line]
    series: Dict[str, Series]

    def in_scope(self, key: str) -> bool:
        s = self.series[key]
        return s.position < len(TIERS) or self.lines[s.line_id].keep_all

    def tier(self, key: str) -> Optional[str]:
        s = self.series[key]
        if s.position < len(TIERS):
            return TIERS[s.position]
        return TIERS[-1] if self.lines[s.line_id].keep_all else None

    def chip_series(self, family: str, gen: str) -> Optional[Series]:
        token = f"{family}:{gen}"
        for s in self.series.values():
            if token in s.chips:
                return s
        return None

    def chip_gens(self, family: str) -> List[str]:
        prefix = f"{family}:"
        return [c[len(prefix):] for s in self.series.values() for c in s.chips if c.startswith(prefix)]


def line_id(brand: str, category: str) -> str:
    return f"{brand.strip().lower()}-{category.strip().lower()}"


def parse_generations(text: str, source: str = "generations.toml") -> Generations:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise GenerationsError(f"{source}: not valid TOML: {e}") from e

    raw_lines = data.get("line")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise GenerationsError(f"{source}: no [[line]] blocks")

    lines: Dict[str, Line] = {}
    series: Dict[str, Series] = {}
    chip_owner: Dict[str, str] = {}
    for raw in raw_lines:
        lid = raw.get("id")
        if lid not in KNOWN_LINES:
            raise GenerationsError(f"{source}: unknown line id {lid!r}; expected one of {KNOWN_LINES}")
        if lid in lines:
            raise GenerationsError(f"{source}: duplicate line {lid!r}")
        keep_all = raw.get("keep_all", False)
        if not isinstance(keep_all, bool):
            raise GenerationsError(f"{source}: line {lid}: keep_all must be true or false")
        entries = raw.get("series")
        if not isinstance(entries, list) or not entries:
            raise GenerationsError(f"{source}: line {lid} has no series")

        built: List[Series] = []
        for position, entry in enumerate(entries):
            key = entry.get("key") if isinstance(entry, dict) else None
            if not isinstance(key, str) or not _KEY_RE.match(key):
                raise GenerationsError(
                    f"{source}: line {lid}: series key {key!r} must be lowercase letters, digits and '-'"
                )
            if key in series:
                raise GenerationsError(f"{source}: duplicate series key {key!r}")
            label = entry.get("label")
            if not isinstance(label, str) or not label.strip():
                raise GenerationsError(f"{source}: series {key}: label is empty")
            chips = entry.get("chips", [])
            if not isinstance(chips, list) or not all(isinstance(c, str) and _CHIP_RE.match(c) for c in chips):
                raise GenerationsError(f"{source}: series {key}: each chip must look like 'family:gen', e.g. 'ryzen:9'")
            for chip in chips:
                if chip in chip_owner:
                    raise GenerationsError(f"{source}: chip {chip} is listed under both {chip_owner[chip]} and {key}")
                chip_owner[chip] = key
            s = Series(key=key, label=label.strip(), line_id=lid, position=position, chips=tuple(chips))
            built.append(s)
            series[key] = s
        lines[lid] = Line(id=lid, keep_all=keep_all, series=tuple(built))

    return Generations(lines=lines, series=series)


def load_generations(path=GENERATIONS_PATH) -> Generations:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise GenerationsError(f"{p}: file not found") from e
    return parse_generations(text, str(p))


@lru_cache(maxsize=1)
def default_generations() -> Generations:
    return load_generations()
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest unit_testing/test_generations.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add db/generations.toml db/generations.py config.py unit_testing/test_generations.py
git commit -F - <<'EOF'
feat(watchlist): db/generations.toml as the one list of series per line (#17)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Watchlist CSV migration + loader (`series`, `status`, derived tier/tracked)

**Files:**
- Modify: `db/watchlist.csv` (header comment block, columns, every row; re-add RX 9070 XTX as retired)
- Modify: `db/watchlist.py`
- Modify: `unit_testing/test_watchlist_validation.py`, `unit_testing/test_seed.py` (loader-level tests only; seed DB tests move in Task 4)
- Test: `unit_testing/test_watchlist_series.py` (new)

**Interfaces:**
- Consumes: Task 1 (`load_generations`, `default_generations`, `line_id`, `Generations`, `GenerationsError`, `config.GENERATIONS_PATH`)
- Produces (in `db/watchlist.py`):
  - `REQUIRED_COLUMNS = ("category", "brand", "model", "spec", "series", "status")`
  - `VALID_STATUSES = ("active", "retired")`
  - `validate_row(row, line_no=None, generations=None) -> dict` — adds `series`, `status`, `gen_tier` (`str | None`: `None` when the series is out of scope), `tracked` (`0`/`1`), `cores`, `vram_gb`
  - `load_all_rows(path=DEFAULT_WATCHLIST_PATH, strict=False, generations_path=DEFAULT_GENERATIONS_PATH) -> list[dict]` — every valid row, active and retired
  - `load_watchlist(path=..., strict=False, generations_path=...) -> list[dict]` — **tracked rows only** (same meaning as today for every caller)
  - `load_retired(path=..., generations_path=...) -> list[dict]` — rows with `tracked == 0` (sinks for the matcher)
  - `load_watchlist_products(path=..., strict=False, generations_path=...) -> list[dict]` — every row shaped for `products`: `category, brand, model, vram_gb, cores, generation_tier (str|None), tracked (0/1), series`
  - `DEFAULT_GENERATIONS_PATH = str(GENERATIONS_PATH)`
  - A bad `generations.toml` raises `GenerationsError` out of every loader (whole-file problem, not a row problem).

- [ ] **Step 1: Convert the CSV**

Run this one-off conversion (it maps each row's current tier to the series at that position in its line, so derived tiers equal today's exactly):

```bash
python - <<'EOF'
import csv, io
from db.generations import load_generations, line_id, TIERS
g = load_generations()
path = "db/watchlist.csv"
text = open(path, encoding="utf-8").read()
out = []
header_done = False
for raw in text.splitlines(keepends=True):
    if raw.startswith("#") or not raw.strip():
        out.append(raw); continue
    row = next(csv.reader([raw.rstrip("\r\n")]))
    if not header_done:
        assert row[:5] == ["category", "brand", "model", "spec", "gen_tier"], row
        out.append("category,brand,model,spec,series,status\n"); header_done = True; continue
    category, brand, model, spec, tier = row[:5]
    line = g.lines[line_id(brand, category)]
    key = line.series[TIERS.index(tier)].key
    buf = io.StringIO(); csv.writer(buf, lineterminator="\n").writerow([category, brand, model, spec, key, "active"])
    out.append(buf.getvalue())
open(path, "w", encoding="utf-8", newline="").write("".join(out))
EOF
```

Then append the retired row (recovered from commit `1fa4d66`) directly after the last `gpu,AMD,...,rx9000,...` row:

```
gpu,AMD,Radeon RX 9070 XTX,32GB,rx9000,retired
```

Rewrite the header comment block's column and maintenance lines (keep the matching paragraph about chip keys unchanged) to:

```
# Columns:
#   category  -- cpu or gpu
#   brand     -- AMD, Intel, NVIDIA
#   model     -- canonical product name (used in DB as 'model')
#   spec      -- cores (CPU) or vram_gb label (GPU), e.g. "16c" or "16GB"
#   series    -- a series key from db/generations.toml (e.g. zen5, rtx50). The
#                tier (current / current-1 / current-2) comes from the series'
#                position there; a series that falls off the end is untracked.
#   status    -- active or retired. NEVER delete a row: set it to retired.
#                seed.py syncs products.tracked both ways from series + status
#                (retired -> tracked=0; back to active -> tracked=1).
```

and replace the old sentences "Deleting a row here does NOT retire a product: retire it via RETIRED_PRODUCTS in migrate.py ..." with: "Retiring a product = status retired (or `python manage_watchlist.py retire <model>`). See ARCHITECTURE Part 2 §7." Update the "seed.py inserts new rows and, on existing rows ... syncs gen_tier" sentence to "syncs series, tier, tracked and the spec facts (cores / VRAM)".

Check: `python -c "import csv;rows=[r for r in csv.reader(l for l in open('db/watchlist.csv',encoding='utf-8') if not l.startswith('#') and l.strip())];print(rows[0], len(rows)-1)"`
Expected: `['category', 'brand', 'model', 'spec', 'series', 'status'] 135`

- [ ] **Step 2: Write the failing tests**

`unit_testing/test_watchlist_series.py`:

```python
"""db/watchlist.py derives tier and tracked from series + status (#17, #18)."""
import pytest

from db.generations import GenerationsError
from db.watchlist import (
    WatchlistRowError, load_all_rows, load_retired, load_watchlist, load_watchlist_products,
)

TOML = """
[[line]]
id = "amd-cpu"
series = [
  { key = "zen5", label = "Ryzen 9000 (Zen 5)" },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)" },
  { key = "zen3", label = "Ryzen 5000 (Zen 3)" },
  { key = "zen2", label = "Ryzen 3000 (Zen 2)" },
]
[[line]]
id = "nvidia-gpu"
series = [{ key = "rtx50", label = "RTX 50" }]
"""

CSV = """# comment
category,brand,model,spec,series,status
cpu,AMD,Ryzen 7 9700X,8c,zen5,active
cpu,AMD,Ryzen 5 8600G,6c,zen4,active
cpu,AMD,Ryzen 7 5800X3D,8c,zen3,retired
cpu,AMD,Ryzen 5 3600,6c,zen2,active
gpu,NVIDIA,GeForce RTX 5070,12GB,rtx50,active
"""


@pytest.fixture
def files(tmp_path):
    toml = tmp_path / "generations.toml"
    toml.write_text(TOML, encoding="utf-8")
    csv_path = tmp_path / "watchlist.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    return str(csv_path), str(toml)


def _by_model(rows):
    return {r["model"]: r for r in rows}


def test_tier_comes_from_series_position(files):
    rows = _by_model(load_all_rows(*files[:1], generations_path=files[1]))
    assert rows["Ryzen 7 9700X"]["gen_tier"] == "current"
    assert rows["Ryzen 5 8600G"]["gen_tier"] == "current-1"


def test_retired_status_untracks(files):
    rows = _by_model(load_all_rows(files[0], generations_path=files[1]))
    assert rows["Ryzen 7 5800X3D"]["tracked"] == 0
    assert rows["Ryzen 7 5800X3D"]["gen_tier"] == "current-2"


def test_series_off_the_end_untracks_with_no_tier(files):
    rows = _by_model(load_all_rows(files[0], generations_path=files[1]))
    assert rows["Ryzen 5 3600"]["tracked"] == 0
    assert rows["Ryzen 5 3600"]["gen_tier"] is None


def test_load_watchlist_returns_tracked_rows_only(files):
    models = [r["model"] for r in load_watchlist(files[0], generations_path=files[1])]
    assert models == ["Ryzen 7 9700X", "Ryzen 5 8600G", "GeForce RTX 5070"]


def test_load_retired_returns_the_sinks(files):
    models = [r["model"] for r in load_retired(files[0], generations_path=files[1])]
    assert models == ["Ryzen 7 5800X3D", "Ryzen 5 3600"]


def test_products_shape_includes_series_and_tracked(files):
    p = _by_model(load_watchlist_products(files[0], generations_path=files[1]))
    assert p["Ryzen 7 5800X3D"] == {
        "category": "cpu", "brand": "AMD", "model": "Ryzen 7 5800X3D", "vram_gb": None,
        "cores": 8, "generation_tier": "current-2", "tracked": 0, "series": "zen3",
    }


@pytest.mark.parametrize("line, field", [
    ("cpu,AMD,Ryzen 9 9950X,16c,zen9,active", "series"),
    ("cpu,AMD,Ryzen 9 9950X,16c,rtx50,active", "series"),
    ("cpu,AMD,Ryzen 9 9950X,16c,zen5,gone", "status"),
])
def test_bad_series_or_status_is_a_row_error(tmp_path, files, line, field):
    bad = tmp_path / "bad.csv"
    bad.write_text("category,brand,model,spec,series,status\n" + line + "\n", encoding="utf-8")
    with pytest.raises(WatchlistRowError) as exc:
        load_all_rows(str(bad), strict=True, generations_path=files[1])
    assert exc.value.field == field
    assert load_all_rows(str(bad), generations_path=files[1]) == []  # non-strict: skipped


def test_broken_generations_file_raises(tmp_path, files):
    broken = tmp_path / "broken.toml"
    broken.write_text("[[line]]\nid = 'nope'\n", encoding="utf-8")
    with pytest.raises(GenerationsError):
        load_watchlist(files[0], generations_path=str(broken))
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest unit_testing/test_watchlist_series.py -q`
Expected: FAIL — `ImportError: cannot import name 'load_all_rows'`

- [ ] **Step 4: Implement the loader changes in `db/watchlist.py`**

1. Imports: add `from config import GENERATIONS_PATH, WATCHLIST_PATH` and `from db.generations import Generations, load_generations, line_id`. Add `DEFAULT_GENERATIONS_PATH = str(GENERATIONS_PATH)`.
2. Replace the constants:

```python
REQUIRED_COLUMNS = ("category", "brand", "model", "spec", "series", "status")
VALID_CATEGORIES = ("cpu", "gpu")
VALID_BRANDS = ("AMD", "Intel", "NVIDIA")
VALID_STATUSES = ("active", "retired")
```

(delete `VALID_GEN_TIERS`; `grep -rn VALID_GEN_TIERS` and update any importer to `db.generations.TIERS`).

3. In `validate_row(row, line_no=None, generations=None)`: replace the `gen_tier` block with

```python
    gens = generations if generations is not None else load_generations()
    series = (row["series"] or "").strip()
    if series not in gens.series:
        raise WatchlistRowError(f"{row['series']!r} is not a series in generations.toml", line_no, "series")
    expected_line = line_id(brand, category)
    if gens.series[series].line_id != expected_line:
        raise WatchlistRowError(
            f"series {series!r} belongs to {gens.series[series].line_id}, not {expected_line}", line_no, "series"
        )
    status = (row["status"] or "").strip().lower()
    if status not in VALID_STATUSES:
        raise WatchlistRowError(f"{row['status']!r} is not one of {VALID_STATUSES}", line_no, "status")
    gen_tier = gens.tier(series)
    tracked = 1 if status == "active" and gens.in_scope(series) else 0
```

and return `series`, `status`, `gen_tier`, `tracked` in the dict (drop `search_aliases` filtering stays). Update the docstring.

4. `_valid_rows(path, strict, generations_path)` loads `gens = load_generations(generations_path)` once (a `GenerationsError` propagates) and passes it to `validate_row`.
5. Public loaders:

```python
def load_all_rows(path=DEFAULT_WATCHLIST_PATH, strict=False, generations_path=DEFAULT_GENERATIONS_PATH):
    """Every usable row, active and retired, with series/status/gen_tier/tracked."""
    return _valid_rows(path, strict, generations_path)


def load_watchlist(path=DEFAULT_WATCHLIST_PATH, strict=False, generations_path=DEFAULT_GENERATIONS_PATH):
    """Tracked rows only: what the scrapers write snapshots for."""
    return [r for r in _valid_rows(path, strict, generations_path) if r["tracked"]]


def load_retired(path=DEFAULT_WATCHLIST_PATH, generations_path=DEFAULT_GENERATIONS_PATH):
    """Untracked rows: still matched by the scrapers as sinks, never written (#18)."""
    return [r for r in _valid_rows(path, False, generations_path) if not r["tracked"]]


def load_watchlist_products(path=DEFAULT_WATCHLIST_PATH, strict=False, generations_path=DEFAULT_GENERATIONS_PATH):
    return [
        {
            "category": r["category"], "brand": r["brand"], "model": r["model"],
            "vram_gb": r["vram_gb"], "cores": r["cores"],
            "generation_tier": r["gen_tier"], "tracked": r["tracked"], "series": r["series"],
        }
        for r in _valid_rows(path, strict, generations_path)
    ]
```

- [ ] **Step 5: Update existing watchlist tests**

- `unit_testing/test_seed.py` `TestLoadWatchlist`: `test_tracked_is_true` becomes "every `active` row in an in-scope series is tracked; the RX 9070 XTX is not" ; `test_all_have_valid_tier` asserts tier in `TIERS` for tracked rows only; `test_every_category_covers_every_tier` already filters on `tracked`.
- `unit_testing/test_watchlist_validation.py`: replace any `gen_tier` column fixture rows with `series,status` (`zen5,active` etc.) and pass `generations_path` to a temp toml where the test writes its own CSV. The `SPECS_UNAVAILABLE_UPSTREAM` exact-set tests (around `:196-209`) must compare against **tracked** models only: build the model set from `load_watchlist()` (tracked) not from raw CSV rows.
- `grep -rn "gen_tier" unit_testing | grep -v watchlist_gen_tier` and fix each fixture CSV header the same way.

- [ ] **Step 6: Run the suite**

Run: `python -m pytest -q`
Expected: PASS except tests owned by later tasks (`test_migrate.py` RETIRED_PRODUCTS pairing — fixed in Task 3; `test_discover_rules.py` table pin — fixed in Task 6). Note the exact failing test names in the commit body if any remain.

- [ ] **Step 7: Commit**

```bash
git add db/watchlist.csv db/watchlist.py unit_testing/
git commit -F - <<'EOF'
feat(watchlist): series + status columns; tier and tracked derived (#17 #18)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Schema + migration (`products.series`, `generations` table); remove `RETIRED_PRODUCTS`

**Files:**
- Modify: `db/schema.sql`
- Modify: `migrate.py` (new step; delete `RETIRED_PRODUCTS` + `migrate_untrack_retired_products` and its call in `main`)
- Modify: `unit_testing/test_migrate.py` (drop the RETIRED_PRODUCTS tests incl. the CSV pairing test near `:600-610`; add new ones)
- Modify: `unit_testing/test_schema.py` if it enumerates tables

**Interfaces:**
- Produces: `migrate.migrate_add_generations(conn: sqlite3.Connection, dry_run: bool = False) -> None` (idempotent; adds `products.series TEXT` and the `generations` table). Task 4's `seed.py` calls it.

- [ ] **Step 1: Write the failing tests** (append to `unit_testing/test_migrate.py`, using the file's existing temp-DB fixture pattern)

```python
class TestAddGenerations:
    def _old_db(self, tmp_path):
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "old.db"))
        conn.execute("""CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, brand TEXT, model TEXT,
                        vram_gb INTEGER, cores INTEGER, generation_tier TEXT, tracked INTEGER NOT NULL DEFAULT 1)""")
        return conn

    def test_adds_series_column_and_generations_table(self, tmp_path):
        from migrate import check_column_exists, check_table_exists, migrate_add_generations
        conn = self._old_db(tmp_path)
        migrate_add_generations(conn)
        assert check_column_exists(conn, "products", "series")
        assert check_table_exists(conn, "generations")

    def test_idempotent(self, tmp_path):
        from migrate import migrate_add_generations
        conn = self._old_db(tmp_path)
        migrate_add_generations(conn)
        migrate_add_generations(conn)  # no "duplicate column" error

    def test_dry_run_writes_nothing(self, tmp_path):
        from migrate import check_column_exists, migrate_add_generations
        conn = self._old_db(tmp_path)
        migrate_add_generations(conn, dry_run=True)
        assert not check_column_exists(conn, "products", "series")

    def test_schema_sql_matches_migration(self, tmp_path):
        import sqlite3
        from config import SCHEMA_PATH
        from migrate import check_column_exists, check_table_exists
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert check_column_exists(conn, "products", "series")
        assert check_table_exists(conn, "generations")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_migrate.py -q -k Generations`
Expected: FAIL — `ImportError: cannot import name 'migrate_add_generations'`

- [ ] **Step 3: Implement**

`db/schema.sql`: in `CREATE TABLE products` add after `generation_tier`:

```sql
    series              TEXT,                            -- db/generations.toml key (#17); NULL for holding/unknown rows
```

and add after the products table:

```sql
-- Mirror of db/generations.toml, rewritten by seed.py on every run (#17).
-- The dashboard reads series labels from here, so a relabel or a launch needs
-- no web rebuild.
CREATE TABLE generations (
    series_key  TEXT    PRIMARY KEY,
    line_id     TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    position    INTEGER NOT NULL,
    keep_all    INTEGER NOT NULL DEFAULT 0
);
```

`migrate.py` (follow the style of `migrate_add_discovery_tables`):

```python
GENERATIONS_DDL = """CREATE TABLE IF NOT EXISTS generations (
    series_key  TEXT    PRIMARY KEY,
    line_id     TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    position    INTEGER NOT NULL,
    keep_all    INTEGER NOT NULL DEFAULT 0
)"""


def migrate_add_generations(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Add products.series and the generations table (#17). Idempotent.

    seed.py calls this itself: at container boot seed runs BEFORE migrate.py,
    and it needs both to exist on an old volume.
    """
    need_column = not check_column_exists(conn, "products", "series")
    need_table = not check_table_exists(conn, "generations")
    if not (need_column or need_table):
        LOGGER.info("  [SKIP] products.series and generations already exist")
        return
    if dry_run:
        LOGGER.info("  [DRY-RUN] Would add products.series=%s generations=%s", need_column, need_table)
        return
    if need_column:
        conn.execute("ALTER TABLE products ADD COLUMN series TEXT")
    if need_table:
        conn.execute(GENERATIONS_DDL)
    conn.commit()
    LOGGER.info("  [MIGRATE] Added products.series / generations table")
```

Register it in `main()`'s ordered step list (same pattern as the other steps). Delete `RETIRED_PRODUCTS`, `migrate_untrack_retired_products`, its `main()` call, and the comment block above them (the CSV's `retired` status replaces it; seed applies it). `grep -rn RETIRED_PRODUCTS` must return nothing outside `docs/`.

- [ ] **Step 4: Run**

Run: `python -m pytest unit_testing/test_migrate.py unit_testing/test_schema.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db/schema.sql migrate.py unit_testing/test_migrate.py unit_testing/test_schema.py
git commit -F - <<'EOF'
feat(db): products.series + generations table; RETIRED_PRODUCTS folded into the CSV (#17 #18)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: `seed.py` — generations mirror, two-way `tracked` sync, bulk guard, boot tolerance

**Files:**
- Modify: `seed.py`
- Modify: `deploy/entrypoint.sh:39`, `deploy/entrypoint-single.sh:166` (tolerate a seed refusal)
- Test: `unit_testing/test_seed.py` (DB tests), `unit_testing/test_seed_generations.py` (new), `unit_testing/test_bootstrap_order.py` (new)

**Interfaces:**
- Consumes: Task 1 `load_generations`/`Generations`; Task 2 `load_watchlist_products(path, strict, generations_path)` (rows include `series`, `tracked`, `generation_tier` possibly `None`); Task 3 `migrate_add_generations(conn)`.
- Produces (in `seed.py`):
  - `class BulkChangeError(RuntimeError)` with attribute `flips: list[tuple[str, int, int]]` (model, old, new)
  - `bulk_limit(total_products: int) -> int` = `max(5, total_products // 10)`
  - `sync_generations(conn, gens: Generations, dry_run=False) -> None`
  - `seed_products(conn, products, dry_run=False, allow_bulk=False) -> dict` — stats keys `inserted, skipped, updated, errors, flips` (`flips` is the list); raises `BulkChangeError` before writing anything when over the limit and not `allow_bulk` (in `dry_run` it never raises; it reports)
  - `report_missing(conn, products) -> list[str]` — DB models (brand != 'Unmatched') absent from the CSV
  - CLI: `python seed.py [--dry-run] [--allow-bulk]`; exit `1` on a refusal or a broken toml.

- [ ] **Step 1: Write the failing tests**

`unit_testing/test_seed_generations.py`:

```python
"""seed.py: series/tracked sync, generations mirror, bulk guard (#17 #18)."""
import sqlite3

import pytest

from config import SCHEMA_PATH
from db.generations import parse_generations
from seed import BulkChangeError, bulk_limit, report_missing, seed_products, sync_generations

TOML_TODAY = """
[[line]]
id = "amd-cpu"
series = [
  { key = "zen5", label = "Ryzen 9000 (Zen 5)" },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)" },
  { key = "zen3", label = "Ryzen 5000 (Zen 3)" },
]
"""
TOML_ZEN6 = TOML_TODAY.replace('series = [\n', 'series = [\n  { key = "zen6", label = "Ryzen 10000 (Zen 6)" },\n', 1)


def _db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _rows(toml_text, statuses=None):
    """Products as load_watchlist_products() returns them, for 3 series x N models."""
    g = parse_generations(toml_text)
    models = {"zen5": ["R9 9950X", "R7 9700X"], "zen4": ["R7 7800X3D", "R5 8600G"],
              "zen3": ["R7 5800X", "R7 5700X", "R5 5600", "R5 5500", "R9 5900X", "R9 5950X", "R5 5600X", "R7 5800X3D"]}
    out = []
    for key, names in models.items():
        for m in names:
            status = (statuses or {}).get(m, "active")
            out.append({"category": "cpu", "brand": "AMD", "model": m, "vram_gb": None, "cores": 8,
                        "generation_tier": g.tier(key), "series": key,
                        "tracked": 1 if status == "active" and g.in_scope(key) else 0})
    return out


def _tracked(conn):
    return dict(conn.execute("SELECT model, tracked FROM products"))


def test_bulk_limit():
    assert bulk_limit(20) == 5
    assert bulk_limit(135) == 13


def test_zen6_rollover_retags_and_untracks_zen3_with_allow_bulk():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    stats = seed_products(conn, _rows(TOML_ZEN6), allow_bulk=True)
    tiers = dict(conn.execute("SELECT model, generation_tier FROM products"))
    assert tiers["R9 9950X"] == "current-1" and tiers["R7 7800X3D"] == "current-2"
    assert tiers["R7 5800X"] == "current-2"  # retired keeps its last tier
    assert {m for m, t in _tracked(conn).items() if t == 0} == {
        "R7 5800X", "R7 5700X", "R5 5600", "R5 5500", "R9 5900X", "R9 5950X", "R5 5600X", "R7 5800X3D"}
    assert len(stats["flips"]) == 8


def test_bulk_change_refused_without_flag_and_nothing_written():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    with pytest.raises(BulkChangeError) as exc:
        seed_products(conn, _rows(TOML_ZEN6))
    assert len(exc.value.flips) == 8
    assert all(t == 1 for t in _tracked(conn).values())
    assert conn.execute("SELECT generation_tier FROM products WHERE model='R9 9950X'").fetchone()[0] == "current"


def test_dry_run_reports_flips_without_raising_or_writing():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    stats = seed_products(conn, _rows(TOML_ZEN6), dry_run=True)
    assert len(stats["flips"]) == 8
    assert all(t == 1 for t in _tracked(conn).values())


def test_retire_and_unretire_one_product():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    seed_products(conn, _rows(TOML_TODAY, {"R7 5800X3D": "retired"}))
    assert _tracked(conn)["R7 5800X3D"] == 0
    seed_products(conn, _rows(TOML_TODAY))
    assert _tracked(conn)["R7 5800X3D"] == 1


def test_truncated_csv_is_not_a_retirement():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    stats = seed_products(conn, _rows(TOML_TODAY)[:2])
    assert stats["flips"] == []
    assert all(t == 1 for t in _tracked(conn).values())
    assert len(report_missing(conn, _rows(TOML_TODAY)[:2])) == 10


def test_new_retired_row_is_inserted_untracked():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY, {"R5 5500": "retired"}))
    assert _tracked(conn)["R5 5500"] == 0


def test_series_is_written():
    conn = _db()
    seed_products(conn, _rows(TOML_TODAY))
    assert conn.execute("SELECT series FROM products WHERE model='R5 8600G'").fetchone()[0] == "zen4"


def test_sync_generations_mirrors_the_toml():
    conn = _db()
    conn.execute("INSERT INTO generations VALUES ('stale', 'amd-cpu', 'Old', 9, 0)")
    sync_generations(conn, parse_generations(TOML_ZEN6))
    rows = conn.execute("SELECT series_key, label, position FROM generations ORDER BY position").fetchall()
    assert rows == [("zen6", "Ryzen 10000 (Zen 6)", 0), ("zen5", "Ryzen 9000 (Zen 5)", 1),
                    ("zen4", "Ryzen 7000 (Zen 4)", 2), ("zen3", "Ryzen 5000 (Zen 3)", 3)]


def test_first_seed_on_old_db_has_zero_flips(tmp_path, monkeypatch):
    """Prod's first boot: DB without products.series/generations; real CSV + toml."""
    import seed
    from db.watchlist import load_watchlist_products
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
        brand TEXT NOT NULL, model TEXT NOT NULL, variant TEXT, vram_gb INTEGER, cores INTEGER,
        generation_tier TEXT, tracked INTEGER NOT NULL DEFAULT 1, last_snapshot_at TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))""")
    for p in load_watchlist_products():
        conn.execute("INSERT INTO products (category, brand, model, vram_gb, cores, generation_tier, tracked)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (p["category"], p["brand"], p["model"], p["vram_gb"], p["cores"],
                      p["generation_tier"] or "current", p["tracked"]))
    conn.commit()
    conn.close()
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    seed.main([])  # must not raise BulkChangeError / SystemExit
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT COUNT(*) FROM products WHERE series IS NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0] >= 14
```

(If `seed.main` resolves `DB_PATH` differently, adjust the monkeypatch to the module attribute it actually reads; do not open `db/trackaroo.db`.)

`unit_testing/test_bootstrap_order.py` — fresh boot cannot revive a retired product:

```python
"""Boot order seed -> migrate -> ingest keeps retired products untracked (#18)."""
import json
import sqlite3

import ingest
import seed
from config import SCHEMA_PATH


def test_ingest_after_seed_keeps_retired_product_untracked(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    seed.seed_products(conn, [{"category": "gpu", "brand": "AMD", "model": "Radeon RX 9070 XTX",
                               "vram_gb": 32, "cores": None, "generation_tier": "current",
                               "tracked": 0, "series": "rx9000"}])
    pid = ingest.find_or_create_product(conn, {"watchlist_category": "gpu", "watchlist_brand": "AMD",
                                               "watchlist_model": "Radeon RX 9070 XTX",
                                               "watchlist_gen_tier": "current"})
    assert conn.execute("SELECT tracked FROM products WHERE id = ?", (pid,)).fetchone()[0] == 0
```

(Check `ingest.find_or_create_product`'s exact signature first — `grep -n "def find_or_create_product" ingest.py` — and call it the way its other tests do.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_seed_generations.py unit_testing/test_bootstrap_order.py -q`
Expected: FAIL — `ImportError: cannot import name 'BulkChangeError'`

- [ ] **Step 3: Implement in `seed.py`**

Add imports: `from config import GENERATIONS_PATH`, `from db.generations import Generations, GenerationsError, load_generations`, `from migrate import migrate_add_generations`. Update the module docstring (it no longer "only inserts").

```python
HOLDING_BRAND = "Unmatched"  # repair_listings.HOLDING_BRAND


class BulkChangeError(RuntimeError):
    """seed would flip `tracked` on too many products at once (#18)."""

    def __init__(self, flips, limit):
        self.flips = flips
        self.limit = limit
        names = ", ".join(f"{m} ({o}->{n})" for m, o, n in flips)
        super().__init__(
            f"Refusing to change tracked on {len(flips)} products (limit {limit}): {names}. "
            "If this is an intended rollover/retirement, re-run with --allow-bulk."
        )


def bulk_limit(total_products: int) -> int:
    return max(5, total_products // 10)


def sync_generations(conn: sqlite3.Connection, gens: Generations, dry_run: bool = False) -> None:
    if dry_run:
        return
    conn.execute("DELETE FROM generations")
    conn.executemany(
        "INSERT INTO generations (series_key, line_id, label, position, keep_all) VALUES (?, ?, ?, ?, ?)",
        [(s.key, s.line_id, s.label, s.position, int(gens.lines[s.line_id].keep_all)) for s in gens.series.values()],
    )
```

Rewrite `seed_products(conn, products, dry_run=False, allow_bulk=False)` as plan-then-apply:

```python
    stats: Dict[str, Any] = {"inserted": 0, "skipped": 0, "updated": 0, "errors": 0, "flips": []}
    updates: List[tuple] = []
    inserts: List[Product] = []
    for p in products:
        existing = conn.execute(
            "SELECT id, generation_tier, vram_gb, cores, tracked, series FROM products"
            " WHERE category = ? AND brand = ? AND model = ?",
            (p["category"], p["brand"], p["model"]),
        ).fetchone()
        if existing is None:
            inserts.append(p)
            continue
        pid, tier, vram, cores, tracked, series = existing
        # A tracked row takes its derived tier; an untracked one keeps where it last sat.
        new_tier = p["generation_tier"] if p["tracked"] and p["generation_tier"] else tier
        wanted = (new_tier, p["vram_gb"], p["cores"], p["tracked"], p["series"])
        if (tier, vram, cores, tracked, series) == wanted:
            stats["skipped"] += 1
            continue
        if tracked != p["tracked"]:
            stats["flips"].append((p["model"], tracked, p["tracked"]))
        updates.append((*wanted, pid))

    total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    limit = bulk_limit(total)
    if len(stats["flips"]) > limit and not allow_bulk and not dry_run:
        raise BulkChangeError(stats["flips"], limit)

    stats["updated"] = len(updates)
    if dry_run:
        stats["inserted"] = len(inserts)
        return stats
    conn.executemany(
        "UPDATE products SET generation_tier = ?, vram_gb = ?, cores = ?, tracked = ?, series = ? WHERE id = ?",
        updates,
    )
    for p in inserts:
        try:
            conn.execute(
                """INSERT INTO products (category, brand, model, vram_gb, cores, generation_tier, tracked, series)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["category"], p["brand"], p["model"], p["vram_gb"], p["cores"],
                 p["generation_tier"] or "current-2", p["tracked"], p["series"]),
            )
            stats["inserted"] += 1
        except sqlite3.IntegrityError as e:
            LOGGER.error("ERROR inserting %s: %s", p["model"], e)
            stats["errors"] += 1
    conn.commit()
    return stats


def report_missing(conn: sqlite3.Connection, products: List[Product]) -> List[str]:
    wanted = {(p["category"], p["brand"], p["model"]) for p in products}
    return [
        model for category, brand, model in conn.execute(
            "SELECT category, brand, model FROM products WHERE brand != ? ORDER BY model", (HOLDING_BRAND,))
        if (category, brand, model) not in wanted
    ]
```

`load_watchlist(path)` in seed.py gains `generations_path: Path = GENERATIONS_PATH` and passes it through.

`main(argv)`:
- add `parser.add_argument("--allow-bulk", action="store_true", help="Allow changing tracked on many products (a rollover)")`;
- load `gens = load_generations()` and products inside `try/except GenerationsError as e: LOGGER.error("%s", e); sys.exit(1)`;
- after `init_db`, call `migrate_add_generations(conn, dry_run=args.dry_run)` (on a dry run against an old DB, skip the product sync if `series` is missing and log that the dry run needs the migration);
- `sync_generations(conn, gens, dry_run=args.dry_run)`;
- `try: stats = seed_products(conn, products, dry_run=args.dry_run, allow_bulk=args.allow_bulk)` / `except BulkChangeError as e: LOGGER.error("%s", e); conn.close(); sys.exit(1)` — nothing was written to `products`;
- log each flip (`"  tracked %s -> %s: %s"`), `"  Tracked changes: %d"`, and each `report_missing` model as a WARNING (`"In the DB but not in watchlist.csv (left unchanged): %s"`).

Entrypoints — a refusal must not stop the container (it runs under `set -e`). Replace the bare `python seed.py` line in both `deploy/entrypoint.sh` and `deploy/entrypoint-single.sh` with:

```sh
# seed.py exits 1 when it refuses a bulk tracked change (a rollover needs
# --allow-bulk, run by hand after reviewing the dry run) or on a broken
# generations.toml. Either way it wrote nothing to products: boot on.
python seed.py || echo "[trackaroo] $(date '+%Y-%m-%d %H:%M:%S') ERROR: seed.py exited non-zero (see above) - products unchanged; run 'python seed.py --dry-run' then '--allow-bulk' if intended"
```

Add to `unit_testing/test_shell_scripts.py` (or the existing entrypoint test file) a test asserting both entrypoints contain `python seed.py ||`.

- [ ] **Step 4: Run**

Run: `python -m pytest -q`
Expected: PASS except Task 6's `test_discover_rules` pin (if still failing).

- [ ] **Step 5: Commit**

```bash
git add seed.py deploy/entrypoint.sh deploy/entrypoint-single.sh unit_testing/
git commit -F - <<'EOF'
feat(seed): mirror generations, sync tracked both ways, bulk guard (#17 #18)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Scrapers — retired rows are matched as sinks and dropped

**Files:**
- Modify: `scraper/scorptec.py` (~`:314`, `:340`), `scraper/pccg.py` (~`:696-715`), `scraper/umart.py` (~`:256-280`)
- Modify: `discover.py:270` (known chips include retired rows)
- Test: `unit_testing/test_retired_sinks.py` (new)

**Interfaces:**
- Consumes: Task 2 `load_watchlist()` (tracked only) and `load_retired()`.
- Produces: no new module. Each scraper builds `Matcher(watchlist + retired)` and treats an index `>= len(watchlist)` as a sink. `watchlist` keeps its current meaning everywhere, so `total_watchlist`, `unmatched_models` and log counts are unchanged.

- [ ] **Step 1: Write the failing test**

Find the narrowest existing seam per scraper (the function that loops scraped items and calls `matcher.resolve`; check how `unit_testing/test_umart.py` / `test_scraper.py` drive it with fixture items and a watchlist). Test, for each of the three scrapers, with watchlist `[GeForce RTX 3060 12GB tracked]` and retired `[GeForce RTX 3060 Ti 8GB]` and scraped titles `"... RTX 3060 Ti 8GB ..."` and `"... RTX 3060 12GB ..."`:

```python
def test_retired_chip_is_a_sink_not_a_sibling_match(...):
    results = <run the scraper's match loop with those inputs>
    models = [r["watchlist_model"] for r in results]
    assert models == ["GeForce RTX 3060"]          # the Ti listing is not filed under the 3060
    assert all(r["watchlist_gen_tier"] for r in results)
```

Also a control test proving the leak exists without sinks is NOT needed; the assertion above fails today because the retired row is absent from the matcher only if chip keys collide — verify with the fixture that today's code yields `["GeForce RTX 3060"]` or a Ti row; if today's chip-key equality already rejects the Ti for the 3060, assert instead that the retired row's listing produces **no** result and that a log line `"dropped 1 listing(s) matched to retired products"` is emitted (caplog).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_retired_sinks.py -q` — Expected: FAIL (no drop log / no `load_retired` use).

- [ ] **Step 3: Implement** (same shape in all three scrapers)

```python
from db.watchlist import load_retired, load_watchlist, WatchlistProduct
...
    watchlist = load_watchlist()
    retired = load_retired()
...
    matcher = Matcher(watchlist + retired)        # retired rows are sinks (#18)
    dropped = 0
...
            i = matcher.resolve(...)
            if i is None:
                continue
            if i >= len(watchlist):
                dropped += 1
                continue
            wp = watchlist[i]
...
    if dropped:
        logger.info("dropped %d listing(s) matched to retired products", dropped)
```

For `pccg.py` the matcher is per category: build `category_retired = [r for r in retired if r["category"] == category]` and `Matcher(category_watchlist + category_retired)`, sink when `local >= len(category_watchlist)`. Where a function receives `watchlist` as a parameter (tests call it), add an optional `retired: Sequence[WatchlistProduct] = ()` parameter instead of loading inside.

`discover.py` `run()`: `wl = watchlist if watchlist is not None else load_watchlist() + load_retired()` so retired chips count as known, not "new parts".

- [ ] **Step 4: Run**

Run: `python -m pytest -q` — Expected: PASS (except Task 6's pin if pending).

- [ ] **Step 5: Commit**

```bash
git add scraper/ discover.py unit_testing/test_retired_sinks.py
git commit -F - <<'EOF'
feat(scrapers): retired watchlist rows are matched as sinks and dropped (#18)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Discovery scope from `generations.toml`

**Files:**
- Modify: `discover_rules.py` (`_GPU_TIERS`, `_RYZEN_TIERS`, `_CORE_TIERS`, `series_tier`, module docstring)
- Modify: `unit_testing/test_discover_rules.py`

**Interfaces:**
- Consumes: Task 1 `Generations.chip_series`, `chip_gens`, `tier`, `default_generations()`.
- Produces: `discover_rules.chip_token(category: str, key: str) -> tuple[str, str] | None`; `series_tier(category, key, generations=None) -> str | None` (same name/return as today; new optional arg).

- [ ] **Step 1: Write the failing tests** (replace the test that pins the old table to the CSV)

```python
from db.generations import parse_generations
from discover_rules import chip_token, series_tier

ZEN6 = open("db/generations.toml", encoding="utf-8").read().replace(
    '{ key = "zen5"', '{ key = "zen6", label = "Ryzen 10000 (Zen 6)", chips = ["ryzen:10"] },\n  { key = "zen5"', 1)


@pytest.mark.parametrize("key, token", [
    ("rtx 5070", ("rtx", "5")), ("rx 9070", ("rx", "9")), ("ryzen 9800x3d", ("ryzen", "9")),
    ("ryzen 8600g", ("ryzen", "8")), ("ryzen 10700x", ("ryzen", "10")), ("ultra 265k", ("ultra", "2")),
    ("core 14400f", ("core", "14")), ("arc b580", ("arc", "b")), ("rtx 6000", None), ("core 400", None),
])
def test_chip_token(key, token):
    assert chip_token("gpu" if key.split()[0] in ("rtx", "rx", "arc") else "cpu", key) == token


@pytest.mark.parametrize("key, tier", [
    ("rtx 5070", "current"), ("rtx 4070", "current-1"), ("rtx 3060", "current-2"), ("rtx 2060", None),
    ("rx 9070", "current"), ("rx 5700", None), ("ryzen 9700x", "current"), ("ryzen 8600g", "current-1"),
    ("ryzen 5600", "current-2"), ("ryzen 3600", None), ("ryzen 10700x", "current"),
    ("ultra 265k", "current"), ("core 14400f", "current-1"), ("core 12400f", None),
    ("arc b580", "current"), ("arc a770", "current-1"), ("arc c770", "current"),
])
def test_series_tier_today_matches_previous_behaviour(key, tier):
    category = "gpu" if key.split()[0] in ("rtx", "rx", "arc") else "cpu"
    assert series_tier(category, key) == tier


def test_after_a_zen6_rollover():
    g = parse_generations(ZEN6)
    assert series_tier("cpu", "ryzen 5600", g) is None
    assert series_tier("cpu", "ryzen 9700x", g) == "current-1"
    assert series_tier("cpu", "ryzen 10700x", g) == "current"
    assert series_tier("cpu", "ryzen 11700x", g) == "current"   # newer than anything known still surfaces
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest unit_testing/test_discover_rules.py -q` — Expected: FAIL (`chip_token` missing).

- [ ] **Step 3: Implement**

Delete `_GPU_TIERS`, `_RYZEN_TIERS`, `_CORE_TIERS`. Add:

```python
from db.generations import Generations, default_generations


def chip_token(category: str, key: str) -> Optional[Tuple[str, str]]:
    """(family, gen) for a chip key, in the terms db/generations.toml's `chips` use."""
    family, _, rest = key.partition(" ")
    digits = _digits(rest)
    if family in ("rtx", "rx"):
        if not digits:
            return None
        # Every GeForce RTX number is d0[5-9]0 (3050..3090, 4060..4090, 5050..5090); anything
        # else ("RTX 6000 Ada", "RTX 4500 Ada", "RTX 5880 Ada") is an Nvidia workstation card.
        if family == "rtx" and not re.fullmatch(r"\d0[5-9]0", digits[:4]):
            return None
        return family, str(int(digits[:4]) // 1000)
    if family == "arc":
        return ("arc", rest[:1]) if rest[:1].isalpha() else None
    if family == "ryzen":
        return ("ryzen", str(int(digits) // 1000)) if digits else None
    if family == "ultra":
        return ("ultra", str(int(digits) // 100)) if digits else None
    if family == "core":
        return ("core", str(int(digits[:2]))) if len(digits) >= 5 else None
    return None


def _newer(gen: str, known: List[str]) -> bool:
    if gen.isdigit() and all(k.isdigit() for k in known):
        return int(gen) > max(int(k) for k in known)
    return gen > max(known)


def series_tier(category: str, key: str, generations: Optional[Generations] = None) -> Optional[str]:
    """In-scope tier for an untracked part, from db/generations.toml.

    A gen listed in a series takes that series' tier (None once it has rolled
    out of scope). A gen NEWER than every listed gen of its family counts as
    'current', so a launch surfaces instead of being dropped; an older unknown
    gen is out of scope.
    """
    gens = generations or default_generations()
    token = chip_token(category, key)
    if token is None:
        return None
    family, gen = token
    series = gens.chip_series(family, gen)
    if series is not None:
        return gens.tier(series.key)
    known = gens.chip_gens(family)
    return "current" if known and _newer(gen, known) else None
```

Update the module docstring: the scope table now lives in `db/generations.toml`. Keep every other function unchanged; `grep -n "series_tier" discover*.py` and check callers still pass `(category, key)`.

- [ ] **Step 4: Run** — `python -m pytest -q` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add discover_rules.py unit_testing/test_discover_rules.py
git commit -F - <<'EOF'
feat(discover): scope tiers come from generations.toml chips (#17)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: Web — tier labels from the `generations` table

**Files:**
- Create: `web/src/lib/server/queries/generations.ts`
- Modify: `web/src/lib/server/repos.ts` (barrel export), `web/src/lib/models.ts` (`TierLabels` type)
- Modify: `web/src/lib/tiers.ts` (delete `TIER_LINE_LABELS`; new signature)
- Modify: `web/src/lib/breadcrumbs.ts`, `web/src/lib/catalogView.ts` (`genOptions`), `web/src/lib/productIndex.ts` (`groupForIndex`), `web/src/routes/product/[id]/+page.svelte`, `web/src/routes/products/+page.svelte`, `web/src/routes/+layout.server.ts`
- Modify: `web/e2e/seed.mjs` (insert generations rows), `web/package.json` (devDependency `smol-toml`)
- Test: `web/test/tiers.test.ts`, `web/test/breadcrumbs.test.ts`, `web/test/catalogView.test.ts`, `web/test/productIndex.test.ts`, new `web/test/generationsQuery.test.ts`; Playwright existing label assertions (e.g. `e2e/app.spec.ts` RTX 50 header) must stay green unchanged.
- Modify: `CHANGELOG.md` (Unreleased line for PR 1)

**Interfaces:**
- Consumes: Task 3's `generations` table (`series_key, line_id, label, position, keep_all`).
- Produces:
  - `export type TierLabels = Record<string, Partial<Record<GenerationTier, string>>>` in `$lib/models`
  - `getTierLabels(db: DB): TierLabels` in `$lib/server/queries/generations.ts` — positions 0/1/2 -> current/current-1/current-2; a `keep_all` line's positions >= 2 never override position 2; returns `{}` when the table is missing (old DB)
  - `generationTierLabel(labels: TierLabels, brand: string, category: string, tier: GenerationTier | null | undefined): string | null`
  - `productBreadcrumbs(p, labels: TierLabels)`, `genOptions(rows, selected, labels: TierLabels)`, `groupForIndex(items, labels: TierLabels)`
  - layout data `tierLabels: TierLabels`

- [ ] **Step 1: Write the failing tests**

`web/test/generationsQuery.test.ts`:

```ts
import Database from 'better-sqlite3';
import { describe, expect, it } from 'vitest';
import { getTierLabels } from '../src/lib/server/queries/generations';

function db(withTable = true) {
	const d = new Database(':memory:');
	if (withTable) {
		d.exec(`CREATE TABLE generations (series_key TEXT PRIMARY KEY, line_id TEXT NOT NULL, label TEXT NOT NULL,
			position INTEGER NOT NULL, keep_all INTEGER NOT NULL DEFAULT 0)`);
		const ins = d.prepare('INSERT INTO generations VALUES (?, ?, ?, ?, ?)');
		ins.run('zen6', 'amd-cpu', 'Ryzen 10000 (Zen 6)', 0, 0);
		ins.run('zen5', 'amd-cpu', 'Ryzen 9000 (Zen 5)', 1, 0);
		ins.run('zen4', 'amd-cpu', 'Ryzen 7000 (Zen 4)', 2, 0);
		ins.run('zen3', 'amd-cpu', 'Ryzen 5000 (Zen 3)', 3, 0);
		ins.run('arc-b', 'intel-gpu', 'Arc B', 0, 1);
		ins.run('arc-a', 'intel-gpu', 'Arc A', 1, 1);
		ins.run('arc-x', 'intel-gpu', 'Arc X', 2, 1);
		ins.run('arc-w', 'intel-gpu', 'Arc W', 3, 1);
	}
	return d;
}

describe('getTierLabels', () => {
	it('maps positions to tiers per line', () => {
		expect(getTierLabels(db())['amd-cpu']).toEqual({
			current: 'Ryzen 10000 (Zen 6)',
			'current-1': 'Ryzen 9000 (Zen 5)',
			'current-2': 'Ryzen 7000 (Zen 4)'
		});
	});
	it('keeps position 2 as the current-2 label on a keep_all line', () => {
		expect(getTierLabels(db())['intel-gpu']['current-2']).toBe('Arc X');
	});
	it('returns {} on a DB without the table', () => {
		expect(getTierLabels(db(false))).toEqual({});
	});
});
```

Update `web/test/tiers.test.ts` to call `generationTierLabel(labels, 'NVIDIA', 'gpu', 'current')` with a literal `labels` object, plus: unknown line falls back to `GENERIC_TIER_LABELS`; `labels = {}` gives generic labels; `null` tier gives `null`. Update `breadcrumbs.test.ts`, `catalogView.test.ts` (`genOptions(rows, selected, LABELS)`), `productIndex.test.ts` (`groupForIndex(items, LABELS)`) to pass a shared literal `LABELS` with today's five lines (put it in `web/test/helpers/tierLabels.ts`).

- [ ] **Step 2: Run to verify failure**

Run (from `web/`): `npx vitest run test/generationsQuery.test.ts test/tiers.test.ts`
Expected: FAIL — module `generations` not found / signature mismatch.

- [ ] **Step 3: Implement**

`web/src/lib/server/queries/generations.ts`:

```ts
// Series labels per product line, from the generations table seed.py mirrors
// out of db/generations.toml (#17). A launch or relabel needs no web rebuild.
import type { DB } from '../db';
import type { GenerationTier } from '$lib/types';
import type { TierLabels } from '$lib/models';

const TIERS: GenerationTier[] = ['current', 'current-1', 'current-2'];

export function getTierLabels(db: DB): TierLabels {
	const has = db
		.prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'generations'")
		.get();
	if (!has) return {};
	const rows = db
		.prepare('SELECT line_id, label, position FROM generations WHERE position < 3 ORDER BY line_id, position')
		.all() as { line_id: string; label: string; position: number }[];
	const out: TierLabels = {};
	for (const r of rows) (out[r.line_id] ??= {})[TIERS[r.position]] = r.label;
	return out;
}
```

Export it from the `repos.ts` barrel. `tiers.ts`:

```ts
import type { TierLabels } from './models';
import type { GenerationTier } from './types';

export const GENERIC_TIER_LABELS: Record<GenerationTier, string> = {
	current: 'Current gen',
	'current-1': 'Previous gen',
	'current-2': 'Two gens back'
};

// Labels come from the DB (getTierLabels, via the root layout's data), so a
// new series shows its own name without a web rebuild (#17).
export function generationTierLabel(
	labels: TierLabels,
	brand: string,
	category: string,
	tier: GenerationTier | null | undefined
): string | null {
	if (!tier) return null;
	const line = `${brand.toLowerCase()}-${category.toLowerCase()}`;
	return labels[line]?.[tier] ?? GENERIC_TIER_LABELS[tier];
}
```

Thread `labels` through `productBreadcrumbs`, `genOptions`, `groupForIndex`. Root layout `load()` adds `tierLabels: memo(db, 'tierLabels', () => getTierLabels(db))`. In `products/+page.svelte` and `product/[id]/+page.svelte` read it with `import { page } from '$app/state'` -> `page.data.tierLabels` (check how other components read layout data, e.g. `productIndex`, and follow that pattern; the types come from `App.PageData` via the layout's return type).

E2E seeding: `cd web && npm install -D smol-toml`. In `web/e2e/seed.mjs`, after the schema is applied:

```js
import { parse as parseToml } from 'smol-toml';
...
function seedGenerations(db) {
	const text = fs.readFileSync(path.resolve(webRoot, '..', 'db', 'generations.toml'), 'utf-8');
	const ins = db.prepare(
		'INSERT OR REPLACE INTO generations (series_key, line_id, label, position, keep_all) VALUES (?, ?, ?, ?, ?)'
	);
	for (const line of parseToml(text).line) {
		line.series.forEach((s, i) => ins.run(s.key, line.id, s.label, i, line.keep_all ? 1 : 0));
	}
}
```

Call it wherever the e2e/vitest DB is built (`grep -rn "SCHEMA_PATH\|schema.sql" web/e2e web/test/helpers`). Add `CHANGELOG.md` under `## Unreleased`: `- Product generations now come from one config file (db/generations.toml); retiring a product is a status in the watchlist instead of a code change (#17, #18).`

- [ ] **Step 4: Run the web gate**

Run (from `web/`): `npm run check && npm test && npm run test:e2e`
Expected: 0 errors; all PASS (existing e2e header assertions such as "RTX 50 (Blackwell)" unchanged).

- [ ] **Step 5: Commit**

```bash
git add web/ CHANGELOG.md
git commit -F - <<'EOF'
feat(web): series labels read from the generations table (#17)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: PR 1 gate, docs touch-up, open PR

**Files:**
- Modify: `STATUS.md` (dated bullet), `CLAUDE.md` test counts, `docs/ARCHITECTURE.md` Part 2 §7 interim note (one paragraph: "series + status columns, see generations.toml; full rewrite with the CLI in PR 3")

- [ ] **Step 1:** Run the full gate: `python -m pytest -q`; from `web/`: `npm run check`, `npm test`, `npm run test:e2e`. Record counts.
- [ ] **Step 2:** Prove "0 flips on today's data" against a **scratch copy of the e2e DB, not db/trackaroo.db**: covered by `test_first_seed_on_old_db_has_zero_flips`; paste its pass line.
- [ ] **Step 3:** Update STATUS/CLAUDE counts, commit (`docs: STATUS for generations PR 1`).
- [ ] **Step 4:** `git push -u origin feat/2026-10-06-generations`; `gh pr create -R 2ndtlmining/Trackaroo --base main --title "Generations config + retirement status (#17 #18)" --body-file <scratch body>` — body lists: what changed, deploy note ("first boot: seed logs `Tracked changes: 0`; verify with `docker compose logs trackaroo | grep 'Tracked changes'`"), and `Closes #17` is NOT used yet (the CLI and docs land in PR 3) — use `Part of #17 #18`.
- [ ] **Step 5:** Tell the owner: wait for all 3 CI jobs green before merging.

---

# Phase 2 — PR 2: the "ready to retire" list

Branch: `feat/2026-10-06-retire-suggestions`, from PR 1's branch (base `main`; merging it ships both if PR 1 is not yet merged).

### Task 9: `retire_suggestions` table + `retire_suggest.py` + daily step + Discord

**Files:**
- Modify: `db/schema.sql`, `migrate.py` (`migrate_add_retire_suggestions`, registered in `main`)
- Modify: `config.py` (`RETIRE_STALE_DAYS = int(os.environ.get("TRACKAROO_RETIRE_STALE_DAYS", "30"))`, `RETIRE_KEEP_DAYS = 90`), `.env.example` (documented, commented out)
- Create: `retire_suggest.py`
- Modify: `run_daily.py` (best-effort step after Discovery, ~`:752`)
- Test: `unit_testing/test_retire_suggest.py`

**Interfaces:**
- Consumes: `products`, `retailer_listings`, `price_snapshots`; `notify_discord.load_dotenv`, `notify_discord.send_embed(webhook, embed) -> bool` (same as `discover.notify_new`).
- Produces:
  - table `retire_suggestions (product_id INTEGER PRIMARY KEY REFERENCES products(id), first_flagged TEXT NOT NULL, last_seen TEXT, last_seen_retailer TEXT, decision TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','requested','kept')), keep_until TEXT, notified INTEGER NOT NULL DEFAULT 0)`
  - `retire_suggest.find_stale(conn, today: date, stale_days: int) -> list[dict]` (keys `product_id, model, last_seen, last_seen_retailer`)
  - `retire_suggest.update(conn, today: date, stale_days: int = RETIRE_STALE_DAYS) -> list[int]` (newly flagged ids)
  - `retire_suggest.build_embed(rows, base_url) -> dict`, `notify_new(conn) -> int`, `run(notify: bool = False, db_path=DB_PATH, today: date | None = None) -> dict`

- [ ] **Step 1: Write the failing tests** (`unit_testing/test_retire_suggest.py`; build a schema.sql DB in `tmp_path` and a helper that inserts a product with `created_at`, a listing and snapshots on given dates)

```python
TODAY = date(2026, 11, 1)

def test_flagged_after_31_days_without_a_snapshot(conn): add("A", created="2026-08-01", snaps=["2026-10-01"]); assert ids(update) == ["A"]
def test_not_flagged_at_29_days(conn): add("B", created="2026-08-01", snaps=["2026-10-03"]); assert update(...) == []
def test_out_of_stock_snapshot_counts_as_live(conn): add("C", snaps=[("2026-10-31", "out_of_stock")]); assert update(...) == []
def test_young_product_never_listed_is_not_flagged(conn): add("D", created="2026-10-22", snaps=[]); assert update(...) == []
def test_old_product_never_listed_is_flagged(conn): add("E", created="2026-08-01", snaps=[]); assert ids(update) == ["E"]
def test_untracked_and_holding_products_are_ignored(conn): ...tracked=0 / brand 'Unmatched' -> []
def test_live_again_removes_pending_and_kept_but_not_requested(conn): ...
def test_kept_reopens_after_keep_until_without_renotify(conn): decision kept, keep_until 2026-10-31, notified 1 -> pending, notified still 1
def test_retired_product_row_is_deleted(conn): row requested, product tracked=0 -> row gone
def test_last_seen_retailer_is_the_latest_snapshots_retailer(conn): ...
def test_notify_sends_once_and_stamps_only_on_success(conn, monkeypatch): send_embed False -> notified stays 0; True -> 1; second call sends nothing
def test_embed_has_no_emoji_and_links_discover(): ...
```

Write each as full code following the helper; assert exact `product_id` lists.

- [ ] **Step 2: Run to verify failure** — `python -m pytest unit_testing/test_retire_suggest.py -q` — Expected: ImportError.

- [ ] **Step 3: Implement**

`find_stale` SQL:

```sql
WITH last AS (
  SELECT l.product_id, s.snapshot_date, l.retailer,
         ROW_NUMBER() OVER (PARTITION BY l.product_id ORDER BY s.snapshot_date DESC, l.retailer) AS rn
  FROM retailer_listings l JOIN price_snapshots s ON s.retailer_listing_id = l.id
)
SELECT p.id AS product_id, p.model, last.snapshot_date AS last_seen, last.retailer AS last_seen_retailer
FROM products p LEFT JOIN last ON last.product_id = p.id AND last.rn = 1
WHERE p.tracked = 1 AND p.brand != 'Unmatched'
  AND date(p.created_at) <= date(:today, '-' || :days || ' days')
  AND (last.snapshot_date IS NULL OR last.snapshot_date < date(:today, '-' || :days || ' days'))
ORDER BY p.model
```

`update()` in one transaction: (1) delete rows whose product is `tracked = 0`; (2) delete `pending`/`kept` rows whose product is not in the stale set; (3) `UPDATE ... SET decision='pending', keep_until=NULL WHERE decision='kept' AND keep_until <= :today`; (4) insert stale products not yet present as `pending` with `first_flagged = today`, refreshing `last_seen`/`last_seen_retailer` on existing rows; return inserted ids. `notify_new` mirrors `discover.notify_new` (title `"Ready to retire"`, one line per product `"**{model}**: last seen {d MMM} at {Retailer}"` or `"never listed"`, footer line `"Retire or Keep each one on the Discover page."`, url `<base>/discover`, color `0x64748B`), stamping `notified = 1` only on a successful send. `run()` opens the DB, returns early with `{"skipped": "no table"}` if the table is missing, calls `update`, then `notify_new` when `notify`.

`run_daily.py`, after the Discovery step:

```python
            def _run_retire_suggest() -> Any:
                import retire_suggest
                return retire_suggest.run(notify=notify_enabled(args))

            best_effort("Retire suggestions", _run_retire_suggest)
```

Add a `test_run_daily.py` case asserting the step is called and that its exception does not fail the run (follow the Discovery step's existing test).

- [ ] **Step 4: Run** — `python -m pytest -q` — PASS.
- [ ] **Step 5: Commit** — `feat(pipeline): daily ready-to-retire list with Discord notice` (heredoc + trailer).

---

### Task 10: `/discover` "Ready to retire" section

**Files:**
- Create: `web/src/lib/server/retire.ts`, `web/src/lib/components/RetireSuggestions.svelte`
- Modify: `web/src/lib/types.ts` (types), `web/src/routes/discover/+page.server.ts` (load + actions), `web/src/routes/discover/+page.svelte` (render the section)
- Modify: `web/e2e/seed.mjs` (one pending suggestion fixture), `web/e2e/app.spec.ts`
- Test: `web/test/retire.test.ts`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 9 table.
- Produces:
  - types: `RetireDecision = 'pending' | 'requested' | 'kept'`; `RetireAction = 'retire' | 'keep' | 'undo'`; `RetireSuggestion { productId: number; brand: string; category: 'cpu' | 'gpu'; model: string; firstFlagged: string; lastSeen: string | null; lastSeenRetailer: string | null; decision: RetireDecision; keepUntil: string | null }`
  - `getRetireSuggestions(db: DB, today: string): RetireSuggestion[]` — pending + requested always; kept only while `keep_until > today` is NOT shown (hidden); returns `[]` without the table
  - `isRetireAction(v: unknown): v is RetireAction`
  - `applyRetireAction(db, productId, action, today: string): 'ok' | 'not-found' | 'invalid'` — `retire`: pending -> requested; `keep`: pending -> kept, `keep_until = date(today, '+90 days')`; `undo`: requested|kept -> pending, `keep_until = NULL`
  - page actions `retire`, `keep`, `undoRetire` (form field `productId`)

- [ ] **Step 1: Write the failing tests** — `web/test/retire.test.ts` (in-memory better-sqlite3 with the table DDL + a products table): each transition, each invalid transition returns `'invalid'`, unknown id `'not-found'`, missing table -> `[]` and `'not-found'`, kept row hidden from the list, ordering (requested after pending, then model). E2E: on `/discover` the "Ready to retire" heading and the fixture's model are visible; clicking Retire shows "Requested" after `networkidle`; a POST to `?/retire` with a non-existent `productId` returns 404 (use `page.request.post` with the form-encoded body) — the Review Focus item.
- [ ] **Step 2: Run to verify failure** — `npx vitest run test/retire.test.ts` — FAIL.
- [ ] **Step 3: Implement** — mirror `$lib/server/discover.ts` (`ACTIONS` table with `from`/`to`, a `hasTable` guard) and the existing `act()` in `+page.server.ts` (validate `productId` integer > 0, `fail(400|404)`, `redirect(303, '/discover')`). `RetireSuggestions.svelte` follows the look of the existing discover sections (read `+page.svelte` first): a section heading "Ready to retire" with a Lucide `Archive` icon, an explanatory line ("Tracked parts no retailer has listed for 30 days. Retire asks for the watchlist change; Keep hides one for 90 days."), one row per suggestion with model, "last seen 3 Sep at PCCG" (or "never listed"), and the two buttons (`Archive` icon "Retire", `Clock` icon "Keep"); requested rows show a "Requested" badge and an "Undo" button. Hide the whole section when the list is empty. Keep each file <= 350 lines. CHANGELOG Unreleased: `- The Discover page lists tracked parts no retailer has sold for 30 days, to retire or keep.`
- [ ] **Step 4: Run the web gate** — `npm run check && npm test && npm run test:e2e` — PASS.
- [ ] **Step 5: Commit** — `feat(web): Ready to retire section on /discover` (heredoc + trailer).
- [ ] **Step 6:** Full gate (pytest too), STATUS bullet, push, `gh pr create -R 2ndtlmining/Trackaroo --base main` ("Ready-to-retire list"), tell the owner to wait for 3 green jobs.

---

# Phase 3 — PR 3: `manage_watchlist.py` + docs (#19)

Branch: `feat/2026-10-06-watchlist-cli`, from PR 2's branch (base `main`).

### Task 11: `watchlist_edit.py` (pure text edits) + `rollover`, `retire`, `check`

**Files:**
- Create: `watchlist_edit.py` (no I/O beyond what callers pass; pure `str -> str` functions)
- Create: `manage_watchlist.py`
- Test: `unit_testing/test_watchlist_edit.py`, `unit_testing/test_manage_watchlist.py`

**Interfaces:**
- Consumes: Task 1 `parse_generations`, Task 2 `validate_row`/`read_watchlist_rows`, `scraper.chip_key.chip_key(text, category)`, `sync_specs.SPECS_UNAVAILABLE_UPSTREAM`.
- Produces:
  - `watchlist_edit.insert_series(toml_text: str, line_id: str, key: str, label: str, chips: list[str]) -> str` — inserts `  { key = "...", label = "...", chips = [...] },` as the first entry after `series = [` in that line's block; raises `ValueError` if the line is missing or the key exists
  - `watchlist_edit.set_status(csv_text: str, models: set[str], status: str) -> tuple[str, list[str]]` — returns new text and the models changed (case-insensitive exact model match); comment lines and line endings untouched
  - `watchlist_edit.append_row(csv_text: str, row: list[str], after_series: str | None, line_id: str) -> str` — inserts after the last row of `after_series`, else after the last row of that line, else at the end; preserves the file's newline style
  - `watchlist_edit.unified(old: str, new: str, name: str) -> str` (difflib)
  - `manage_watchlist.main(argv) -> int` with subcommands `rollover`, `retire`, `check` (Task 12 adds `add`, `reassign`); module constants `CSV_PATH`, `TOML_PATH` (from config; tests monkeypatch them)

- [ ] **Step 1: Write the failing tests**

`unit_testing/test_watchlist_edit.py` — full tests for: `insert_series` puts zen6 first in amd-cpu only and the result parses with `parse_generations` with zen6 at position 0; duplicate key raises; unknown line raises. `set_status` flips exactly the named rows, leaves comments byte-identical, returns changed models, no-op for already-retired rows. `test_crlf_preserved`: a CRLF file comes back CRLF on every line with only the edited line changed (`old.splitlines(True)` vs `new.splitlines(True)` differ in exactly one index). `append_row` placement in the three cases.

`unit_testing/test_manage_watchlist.py` (monkeypatch `CSV_PATH`/`TOML_PATH` to tmp copies of the real files; a `DB_PATH` tmp DB where needed):

```python
def test_rollover_dry_run_lists_retags_and_retirements_and_writes_nothing(files, capsys):
    before = (files.csv.read_text(), files.toml.read_text())
    assert main(["rollover", "amd-cpu", "--new", "zen6", "--label", "Ryzen 10000 (Zen 6)", "--chips", "ryzen:10", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Ryzen 7 9700X: current -> current-1" in out
    assert "RETIRE Ryzen 5 5600" in out
    assert (files.csv.read_text(), files.toml.read_text()) == before

def test_rollover_writes_toml_only(files): ...toml has zen6 first; csv unchanged; output tells to run seed.py --allow-bulk
def test_retire_model(files): main(["retire", "Ryzen 7 5800X3D"]) -> csv row status retired
def test_retire_series(files): all zen3 rows retired
def test_retire_unknown_model_exits_1(files)
def test_retire_stale_reads_pending_and_requested(files, db): two suggestions -> both retired in csv
def test_check_passes_on_the_real_files(files): main(["check"]) == 0
def test_check_fails_on_chip_collision(files): append duplicate (same chip key + spec) -> 1 with the two models named
def test_check_fails_on_orphan_specs_unavailable(files, monkeypatch): add a fake key to SPECS_UNAVAILABLE_UPSTREAM -> 1
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest unit_testing/test_watchlist_edit.py unit_testing/test_manage_watchlist.py -q` — ImportError.
- [ ] **Step 3: Implement**
  - `rollover`: read both files; `new_toml = insert_series(...)`; derive old/new rows with `validate_row(row, n, parse_generations(old|new))` for every CSV row; print `"{model}: {old_tier} -> {new_tier}"` for tier changes and `"RETIRE {model}"` for tracked 1 -> 0; print the diff of the toml; unless `--dry-run`, write the toml; always end with `"Next: python seed.py --dry-run, then python seed.py --allow-bulk (on the host after deploy)."`
  - `retire <model> | --series KEY | --stale`: build the model set (series: every row with that series; stale: `SELECT p.model FROM retire_suggestions r JOIN products p ON p.id = r.product_id WHERE r.decision IN ('pending','requested')` against `config.DB_PATH`, opened read-only via `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`); `set_status(..., "retired")`; print diff; write unless `--dry-run`; exit 1 if a named model is not found.
  - `check`: (1) `parse_generations` of the toml; (2) every CSV row through `validate_row` strictly, collecting **all** errors (not stopping at the first); (3) collisions: group all rows by `(category, chip_key(model, category), spec)` — any group > 1 is an error naming the models; a row whose `chip_key` is `None` is an error; (4) every `SPECS_UNAVAILABLE_UPSTREAM` key must be a CSV model; print `"OK: N rows, M series"` or each problem; exit 0/1.
  - Writes use `open(path, "w", encoding="utf-8", newline="")` so line endings are the text's own.
- [ ] **Step 4: Run** — `python -m pytest -q` — PASS.
- [ ] **Step 5: Commit** — `feat(cli): manage_watchlist.py rollover/retire/check (#19)`.

---

### Task 12: `add` and `reassign`

**Files:**
- Modify: `manage_watchlist.py`
- Test: `unit_testing/test_manage_watchlist.py`

**Interfaces:**
- Consumes: Task 11 helpers; `backup_db.backup_database(...)` (read its signature at `backup_db.py:203` and call it the way `run_daily.py` does).
- Produces: subcommands `add "<model>" --spec <16c|16GB> --series <key>` and `reassign <listing_id> "<model>" [--dry-run]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_add_appends_after_its_series_and_lists_follow_ups(files, capsys):
    assert main(["add", "Ryzen 7 10700X", "--spec", "8c", "--series", "zen5"]) == 0
    rows = [l for l in files.csv.read_text().splitlines() if l.startswith("cpu,AMD,")]
    assert "cpu,AMD,Ryzen 7 10700X,8c,zen5,active" in rows
    out = capsys.readouterr().out
    assert "launch_msrp.json" in out and "perf_index.json" in out

def test_add_infers_brand_and_category_from_the_series(files): "GeForce RTX 5070 SUPER" --spec 18GB --series rtx50 -> "gpu,NVIDIA,..."
def test_add_refuses_a_chip_collision(files): "GeForce RTX 5070" --spec 12GB --series rtx50 -> exit 1, csv unchanged
def test_add_allows_same_chip_different_vram(files): existing 16GB chip + new 8GB row -> ok
def test_add_rejects_bad_spec_and_unknown_series(files)
def test_add_dry_run_writes_nothing(files)
def test_reassign_dry_run_prints_listing_and_snapshot_count(db, capsys)
def test_reassign_moves_listing_and_leaves_snapshots_byte_identical(db):
    before = db.execute("SELECT * FROM price_snapshots ORDER BY id").fetchall()
    assert main(["reassign", str(listing_id), "GeForce RTX 3060 Ti"]) == 0
    assert db.execute("SELECT product_id FROM retailer_listings WHERE id=?", (listing_id,)).fetchone()[0] == ti_id
    assert db.execute("SELECT * FROM price_snapshots ORDER BY id").fetchall() == before
def test_reassign_takes_a_backup_first(db, monkeypatch): backup function called before the UPDATE
def test_reassign_unknown_listing_or_ambiguous_model_exits_1(db)
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — `add`: series -> line -> brand (`{"amd": "AMD", "intel": "Intel", "nvidia": "NVIDIA"}`) and category; validate the new row with `validate_row`; collision check as in `check` but including the new row; `append_row`; print diff + follow-ups (`db/launch_msrp.json` MSRP, `db/perf_index.json` entry, "specs: run sync_specs.py after the first scrape; if upstream has none, add to SPECS_UNAVAILABLE_UPSTREAM"). `reassign`: open `config.DB_PATH` read-write; look up the listing (`id, retailer, variant_name, product_id`) and target product by exact model (error if 0 or > 1, listing the candidates with brand/category); dry run prints `"listing {id} {retailer} '{variant}' : {old model} -> {new model} ({n} snapshots stay attached)"`; real run calls the backup first, then `UPDATE retailer_listings SET product_id = ? WHERE id = ?`, commits, prints the same line.
- [ ] **Step 4: Run** — `python -m pytest -q` — PASS.
- [ ] **Step 5: Commit** — `feat(cli): manage_watchlist.py add + reassign (#19)`.

---

### Task 13: Docs, CI check, PR 3

**Files:**
- Modify: `docs/ARCHITECTURE.md` Part 2: replace the per-line tier tables in §1-§5 with a pointer to `db/generations.toml` (keep the prose rules: 2-generation limit, Arc keep_all, exclusions); rewrite §7 around the CLI: launch day (rollover -> add -> MSRP/perf -> check -> PR -> redeploy -> `docker compose exec trackaroo python seed.py --dry-run` then `--allow-bulk`), retiring one part (`retire` or the /discover Retire button -> PR), un-retiring (status back to active), fixing a mis-filed listing (`reassign` on the host), what seed's bulk guard does.
- Modify: `README.md` (one "Managing the watchlist" paragraph pointing at §7), `.github/workflows/ci.yml` backend job: `- run: python manage_watchlist.py check` after pytest, `CHANGELOG.md` Unreleased line, `STATUS.md` bullet, `CLAUDE.md` counts + a Pipeline-conventions bullet: "Generations live in db/generations.toml; never hand-edit tiers or delete watchlist rows (status retired); seed's bulk guard needs --allow-bulk for a rollover."
- Modify: `discover_rules.py` docstring / `test_discover_rules` mentions of "update this table and Part 2 together" if any remain.

- [ ] **Step 1:** Make the doc edits.
- [ ] **Step 2:** Add a pytest test `unit_testing/test_ci_guards.py::test_ci_runs_watchlist_check` asserting `ci.yml` contains `python manage_watchlist.py check`.
- [ ] **Step 3:** Full gate (pytest, check, vitest, Playwright).
- [ ] **Step 4:** Commit `docs: ARCHITECTURE §7 around manage_watchlist.py; CI runs check (#19)`; push; `gh pr create -R 2ndtlmining/Trackaroo --base main` with `Closes #17`, `Closes #18`, `Closes #19`; tell the owner to wait for 3 green jobs, then `python release.py 0.9.0` on the PC, tag, redeploy outside 04:00-09:59, then on the host: `docker compose logs trackaroo | grep "Tracked changes"` (want 0) and `docker compose exec trackaroo python manage_watchlist.py check`.
