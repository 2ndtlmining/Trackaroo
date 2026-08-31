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

from config import WATCHLIST_PATH

logger = logging.getLogger(__name__)

WatchlistProduct = Dict[str, Any]

DEFAULT_WATCHLIST_PATH = str(WATCHLIST_PATH)

REQUIRED_COLUMNS = ("category", "brand", "model", "spec", "gen_tier", "search_aliases")
VALID_CATEGORIES = ("cpu", "gpu")
VALID_BRANDS = ("AMD", "Intel", "NVIDIA")
VALID_GEN_TIERS = ("current", "current-1", "current-2")

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


def validate_row(row: Dict[str, str], line_no: Optional[int] = None) -> Dict[str, Any]:
    """Validate one raw CSV row and return it with the spec parsed.

    Args:
        row: Raw row dict from csv.DictReader.
        line_no: CSV line number, for the error message.

    Returns:
        The row plus ``cores``, ``vram_gb`` and ``search_terms``.

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

    gen_tier = (row["gen_tier"] or "").strip()
    if gen_tier not in VALID_GEN_TIERS:
        raise WatchlistRowError(
            f"{row['gen_tier']!r} is not one of {VALID_GEN_TIERS}", line_no, "gen_tier"
        )

    search_terms = _parse_search_terms(row["search_aliases"])
    if not search_terms:
        raise WatchlistRowError(
            "no search aliases; the scrapers would never match this product",
            line_no,
            "search_aliases",
        )

    spec_fields = parse_spec(row["spec"], category, line_no)

    return {
        **row,
        "category": category,
        "brand": brand,
        "model": model,
        "gen_tier": gen_tier,
        "cores": spec_fields["cores"],
        "vram_gb": spec_fields["vram_gb"],
        "search_terms": search_terms,
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


def _valid_rows(path: str, strict: bool) -> List[Dict[str, Any]]:
    """Validate every row, skipping (and reporting) the ones that fail.

    Skipping rather than raising is deliberate: a typo in one row should cost
    that one product, not stop the container from booting.
    """
    validated: List[Dict[str, Any]] = []
    skipped = 0

    for row in read_watchlist_rows(path):
        line_no = row.pop("_line_no", None)
        try:
            validated.append(validate_row(row, line_no))
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


def load_watchlist(
    path: str = DEFAULT_WATCHLIST_PATH, strict: bool = False
) -> List[WatchlistProduct]:
    """Load the watchlist for scraper use.

    Returns rows enriched with parsed ``cores``/``vram_gb`` (from the spec
    column) and ``search_terms`` (from the search_aliases column, lowercased).

    Args:
        path: Path to the watchlist CSV (default db/watchlist.csv).
        strict: Raise on the first bad row instead of skipping it. For tooling
            that wants to validate the file, not for the pipeline.

    Returns:
        List of watchlist product dicts, excluding any unusable rows.
    """
    return _valid_rows(path, strict)


def _parse_search_terms(raw: str) -> List[str]:
    """Split a search_aliases column into lowercased, trimmed terms."""
    return [t.strip().lower() for t in (raw or "").split("|") if t.strip()]


def load_watchlist_products(
    path: str = DEFAULT_WATCHLIST_PATH, strict: bool = False
) -> List[WatchlistProduct]:
    """Load the watchlist for database seeding.

    Returns dicts shaped for the ``products`` table (category, brand, model,
    vram_gb, cores, generation_tier, tracked).

    Args:
        path: Path to the watchlist CSV (default db/watchlist.csv).
        strict: Raise on the first bad row instead of skipping it.

    Returns:
        List of product dicts suitable for seeding the DB.
    """
    return [
        {
            "category": row["category"],
            "brand": row["brand"],
            "model": row["model"],
            "vram_gb": row["vram_gb"],
            "cores": row["cores"],
            "generation_tier": row["gen_tier"],
            "tracked": 1,  # All watchlist products are tracked by definition
        }
        for row in _valid_rows(path, strict)
    ]


def watchlist_exists(path: str = DEFAULT_WATCHLIST_PATH) -> bool:
    """Return True if the watchlist CSV exists at the given path."""
    from pathlib import Path
    return Path(path).exists()
