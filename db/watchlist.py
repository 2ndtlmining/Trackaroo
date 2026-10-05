"""Shared watchlist loading utilities for Trackaroo.

Loads `db/watchlist.csv` into normalized dicts used by both the scrapers
(scraper/scorptec.py, scraper/pccg.py, scraper/umart.py) and the seeder
(seed.py). Centralising this avoids three copies of the same CSV-parsing +
spec-parsing logic.

**One bad row costs one product, never the whole run.** Until 31-Aug-2026 this
module parsed the spec column with a literal ``int(spec.replace("GB", ""))``, so
a lowercase ``16gb`` raised ValueError straight out of `load_watchlist`. That
exited `seed.py` with status 1, and `deploy/entrypoint-single.sh` runs
`python seed.py` under `set -e` -- so a one-character typo in a CSV stopped the
container from starting, and broke every scraper on the way. Rows are now
validated individually, reported by line number and field, and skipped.
"""
from __future__ import annotations

import csv
import logging
import re
from typing import Any, Dict, List, Optional

from config import GENERATIONS_PATH, WATCHLIST_PATH
from db.generations import Generations, line_id, load_generations

logger = logging.getLogger(__name__)

WatchlistProduct = Dict[str, Any]

DEFAULT_WATCHLIST_PATH = str(WATCHLIST_PATH)
DEFAULT_GENERATIONS_PATH = str(GENERATIONS_PATH)

# The old sixth column, search_aliases, was retired in #20: matching is exact
# chip-key equality on the model name (scraper/chip_key.py), so aliases were
# never read. A CSV that still has the column loads fine; it is ignored.
REQUIRED_COLUMNS = ("category", "brand", "model", "spec", "series", "status")
VALID_CATEGORIES = ("cpu", "gpu")
VALID_BRANDS = ("AMD", "Intel", "NVIDIA")
VALID_STATUSES = ("active", "retired")

# '16c' / '16 C' for CPUs, '16GB' / '16 gb' for GPUs. The unit is required:
# a bare '12' is ambiguous between cores and gigabytes, so it is rejected
# rather than guessed.
_CPU_SPEC_RE = re.compile(r"^\s*(\d+)\s*c\s*$", re.IGNORECASE)
_GPU_SPEC_RE = re.compile(r"^\s*(\d+)\s*gb\s*$", re.IGNORECASE)


class WatchlistRowError(ValueError):
    """A single watchlist row is unusable. Carries enough to fix the CSV."""

    def __init__(self, message: str, line_no: Optional[int] = None, field: Optional[str] = None):
        self.line_no = line_no
        self.field = field
        where = f"watchlist row {line_no}" if line_no is not None else "watchlist row"
        what = f" [{field}]" if field else ""
        super().__init__(f"{where}{what}: {message}")


def parse_spec(spec: str, category: str, line_no: Optional[int] = None) -> Dict[str, Any]:
    """Parse the spec column into cores (CPU) or vram_gb (GPU).

    Tolerant of case and surrounding spaces, because a human edits this file by
    hand: '16c', '16C' and ' 16 c ' all mean sixteen cores.

    Args:
        spec: Raw spec string from the CSV, e.g. '16c' or '32GB'.
        category: 'cpu' or 'gpu'.
        line_no: CSV line number, used only to make the error message useful.

    Returns:
        Dict with ``cores`` and ``vram_gb`` keys (one of which is None).

    Raises:
        WatchlistRowError: if the spec cannot be understood.
    """
    if category == "cpu":
        match = _CPU_SPEC_RE.match(spec or "")
        if not match:
            raise WatchlistRowError(
                f"cannot read cores from {spec!r}; expected e.g. '16c'", line_no, "spec"
            )
        return {"cores": int(match.group(1)), "vram_gb": None}

    match = _GPU_SPEC_RE.match(spec or "")
    if not match:
        raise WatchlistRowError(
            f"cannot read VRAM from {spec!r}; expected e.g. '16GB'", line_no, "spec"
        )
    return {"cores": None, "vram_gb": int(match.group(1))}


def validate_row(
    row: Dict[str, str],
    line_no: Optional[int] = None,
    generations: Optional[Generations] = None,
) -> Dict[str, Any]:
    """Validate one raw CSV row and return it with spec, tier and tracked derived.

    Args:
        row: Raw row dict from csv.DictReader.
        line_no: CSV line number, for the error message.
        generations: Parsed db/generations.toml (default: the shared one).

    Returns:
        The row plus ``cores``, ``vram_gb``, ``gen_tier`` (None when the series
        is out of scope) and ``tracked`` (1 only for an active, in-scope row).

    Raises:
        WatchlistRowError: naming the offending field, so the CSV can be fixed
            without reading this file.
    """
    for column in REQUIRED_COLUMNS:
        if row.get(column) is None:
            raise WatchlistRowError("column is missing", line_no, column)

    category = (row["category"] or "").strip().lower()
    if category not in VALID_CATEGORIES:
        raise WatchlistRowError(
            f"{row['category']!r} is not one of {VALID_CATEGORIES}", line_no, "category"
        )

    brand = (row["brand"] or "").strip()
    if brand not in VALID_BRANDS:
        raise WatchlistRowError(
            f"{row['brand']!r} is not one of {VALID_BRANDS}", line_no, "brand"
        )

    model = (row["model"] or "").strip()
    if not model:
        raise WatchlistRowError("model is empty", line_no, "model")

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

    spec_fields = parse_spec(row["spec"], category, line_no)

    return {
        **{k: v for k, v in row.items() if k != "search_aliases"},
        "category": category,
        "brand": brand,
        "model": model,
        "series": series,
        "status": status,
        "gen_tier": gen_tier,
        "tracked": tracked,
        "cores": spec_fields["cores"],
        "vram_gb": spec_fields["vram_gb"],
    }


def read_watchlist_rows(path: str = DEFAULT_WATCHLIST_PATH) -> List[Dict[str, str]]:
    """Read the watchlist CSV, skipping comment lines.

    Args:
        path: Path to the watchlist CSV (default db/watchlist.csv).

    Returns:
        Raw row dicts from csv.DictReader, each carrying its 1-based CSV line
        number under ``_line_no`` for error reporting.
    """
    with open(path, encoding="utf-8") as f:
        numbered = [
            (i, line) for i, line in enumerate(f, start=1)
            if not line.startswith("#") and line.strip()
        ]
    if not numbered:
        return []

    line_numbers = [i for i, _ in numbered[1:]]  # the first kept line is the header
    rows = list(csv.DictReader([line for _, line in numbered]))
    for row, line_no in zip(rows, line_numbers):
        row["_line_no"] = line_no
    return rows


def _valid_rows(path: str, strict: bool, generations_path: str) -> List[Dict[str, Any]]:
    """Validate every row, skipping (and reporting) the ones that fail.

    Skipping rather than raising is deliberate: a typo in one row should cost
    that one product, not stop the container from booting.
    """
    gens = load_generations(generations_path)  # a GenerationsError is whole-file: let it raise
    validated: List[Dict[str, Any]] = []
    skipped = 0

    for row in read_watchlist_rows(path):
        line_no = row.pop("_line_no", None)
        try:
            validated.append(validate_row(row, line_no, gens))
        except WatchlistRowError as exc:
            if strict:
                raise
            skipped += 1
            logger.error("Skipping unusable %s", exc)

    if skipped:
        logger.error(
            "Skipped %d unusable watchlist row(s) - those products are NOT tracked "
            "until the CSV is fixed",
            skipped,
        )
    return validated


def load_all_rows(
    path: str = DEFAULT_WATCHLIST_PATH,
    strict: bool = False,
    generations_path: str = DEFAULT_GENERATIONS_PATH,
) -> List[WatchlistProduct]:
    """Every usable row, active and retired, with series/status/gen_tier/tracked.

    Args:
        path: Path to the watchlist CSV (default db/watchlist.csv).
        strict: Raise on the first bad row instead of skipping it.
        generations_path: Path to generations.toml.
    """
    return _valid_rows(path, strict, generations_path)


def load_watchlist(
    path: str = DEFAULT_WATCHLIST_PATH,
    strict: bool = False,
    generations_path: str = DEFAULT_GENERATIONS_PATH,
) -> List[WatchlistProduct]:
    """Tracked rows only: what the scrapers write snapshots for.

    Rows carry parsed ``cores``/``vram_gb`` and a derived ``gen_tier``.
    ``strict`` raises on the first bad row (for validation tooling).
    """
    return [r for r in _valid_rows(path, strict, generations_path) if r["tracked"]]


def load_retired(
    path: str = DEFAULT_WATCHLIST_PATH,
    generations_path: str = DEFAULT_GENERATIONS_PATH,
) -> List[WatchlistProduct]:
    """Untracked rows: still matched by the scrapers as sinks, never written (#18)."""
    return [r for r in _valid_rows(path, False, generations_path) if not r["tracked"]]


def load_watchlist_products(
    path: str = DEFAULT_WATCHLIST_PATH,
    strict: bool = False,
    generations_path: str = DEFAULT_GENERATIONS_PATH,
) -> List[WatchlistProduct]:
    """Every row shaped for the ``products`` table, tracked or not.

    Keys: category, brand, model, vram_gb, cores, generation_tier (None when the
    series is out of scope), tracked (0/1), series.
    """
    return [
        {
            "category": r["category"],
            "brand": r["brand"],
            "model": r["model"],
            "vram_gb": r["vram_gb"],
            "cores": r["cores"],
            "generation_tier": r["gen_tier"],
            "tracked": r["tracked"],
            "series": r["series"],
        }
        for r in _valid_rows(path, strict, generations_path)
    ]


def watchlist_exists(path: str = DEFAULT_WATCHLIST_PATH) -> bool:
    """Return True if the watchlist CSV exists at the given path."""
    from pathlib import Path
    return Path(path).exists()
