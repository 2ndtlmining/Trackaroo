"""Shared watchlist loading utilities for Trackaroo.

Loads `db/watchlist.csv` into normalized dicts used by both the scrapers
(fetch_test.py, scraper/pccg.py) and the seeder (seed.py). Centralising this
avoids three copies of the same CSV-parsing + spec-parsing logic.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

WatchlistProduct = Dict[str, Any]

DEFAULT_WATCHLIST_PATH = "db/watchlist.csv"


def parse_spec(spec: str, category: str) -> Dict[str, Any]:
    """Parse the spec column into cores (CPU) or vram_gb (GPU).

    Args:
        spec: Raw spec string from the CSV, e.g. '16c' or '32GB'.
        category: 'cpu' or 'gpu'.

    Returns:
        Dict with ``cores`` and ``vram_gb`` keys (one of which is None).
    """
    if category == "cpu":
        return {"cores": int(spec.replace("c", "")), "vram_gb": None}
    return {"cores": None, "vram_gb": int(spec.replace("GB", ""))}


def read_watchlist_rows(path: str = DEFAULT_WATCHLIST_PATH) -> List[Dict[str, str]]:
    """Read the watchlist CSV, skipping comment lines.

    Args:
        path: Path to the watchlist CSV (default db/watchlist.csv).

    Returns:
        Raw row dicts from csv.DictReader.
    """
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    return list(csv.DictReader(lines))


def load_watchlist(path: str = DEFAULT_WATCHLIST_PATH) -> List[WatchlistProduct]:
    """Load the watchlist for scraper use.

    Returns rows enriched with parsed ``cores``/``vram_gb`` (from the spec
    column) and ``search_terms`` (from the search_aliases column, lowercased).

    Args:
        path: Path to the watchlist CSV (default db/watchlist.csv).

    Returns:
        List of watchlist product dicts.
    """
    products: List[WatchlistProduct] = []
    for row in read_watchlist_rows(path):
        spec_fields = parse_spec(row["spec"], row["category"])
        products.append({
            **row,
            "cores": spec_fields["cores"],
            "vram_gb": spec_fields["vram_gb"],
            "search_terms": _parse_search_terms(row["search_aliases"]),
        })
    return products


def _parse_search_terms(raw: str) -> List[str]:
    """Split a search_aliases column into lowercased, trimmed terms."""
    return [t.strip().lower() for t in raw.split("|")]


def load_watchlist_products(path: str = DEFAULT_WATCHLIST_PATH) -> List[WatchlistProduct]:
    """Load the watchlist for database seeding.

    Returns dicts shaped for the ``products`` table (category, brand, model,
    vram_gb, cores, generation_tier, tracked).

    Args:
        path: Path to the watchlist CSV (default db/watchlist.csv).

    Returns:
        List of product dicts suitable for seeding the DB.
    """
    products: List[WatchlistProduct] = []
    for row in read_watchlist_rows(path):
        spec_fields = parse_spec(row["spec"], row["category"])
        products.append({
            "category": row["category"],
            "brand": row["brand"],
            "model": row["model"],
            "vram_gb": spec_fields["vram_gb"],
            "cores": spec_fields["cores"],
            "generation_tier": row["gen_tier"],
            "tracked": 1,  # All watchlist products are tracked by definition
        })
    return products


def watchlist_exists(path: str = DEFAULT_WATCHLIST_PATH) -> bool:
    """Return True if the watchlist CSV exists at the given path."""
    return Path(path).exists()
