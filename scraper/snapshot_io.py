"""Safe, atomic writes for the daily scrape snapshots in ``data/``.

Both scrapers emit the same envelope per (category, retailer, date). Writing it
with a plain ``open(path, "w")`` had two failure modes that made those files
unusable as the backup they were meant to be:

1. ``open(..., "w")`` truncates the target *before* writing, so a crash, a
   timeout kill, or a full disk leaves a corrupt half-file where a good
   snapshot used to be.
2. Nothing stopped a re-run from replacing a good file with a worse one. When a
   rate-limited PCCG re-run matched zero products, it overwrote the complete
   snapshot taken earlier the same day. 165 snapshots (19-Aug and 21-Aug PCCG)
   survived only because the DB ingest is idempotent.

``save_snapshot`` fixes both: it writes to a temp file and ``os.replace``s it
into place (atomic on POSIX and Windows), and it refuses to replace a richer
snapshot with a poorer one — the weaker result is parked in a
``.partial-HHMMSS.json`` sidecar instead, so nothing is silently discarded.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)


def build_snapshot(
    retailer: str,
    scrape_date: str,
    category: str,
    total_watchlist: int,
    products: List[Dict[str, Any]],
    unmatched_models: List[str],
) -> Dict[str, Any]:
    """Build the snapshot envelope shared by every scraper.

    Keeping this in one place means `ingest.py` only ever has one shape to
    parse, and a new retailer cannot drift from the format by accident.
    """
    return {
        "retailer": retailer,
        "scrape_date": scrape_date,
        "category": category,
        "total_watchlist": total_watchlist,
        "matched": len(products),
        "unmatched_count": len(unmatched_models),
        "unmatched_models": unmatched_models,
        "products": products,
    }


def snapshot_size(data: Dict[str, Any]) -> int:
    """How many products a snapshot holds.

    Prefers the explicit ``matched`` field but falls back to the length of
    ``products``, so a hand-edited or legacy file still compares sensibly.
    """
    products = data.get("products")
    if isinstance(products, list):
        return len(products)
    matched = data.get("matched")
    return matched if isinstance(matched, int) else 0


def read_snapshot(path: Path) -> Optional[Dict[str, Any]]:
    """Load an existing snapshot, or None if it is missing or unreadable.

    An unreadable file is treated as absent so a corrupt leftover can never
    block a good scrape from being written.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON to ``path`` atomically via a temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Never leave a stray .tmp behind on failure (including KeyboardInterrupt).
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def save_snapshot(
    path: Path,
    data: Dict[str, Any],
    *,
    timestamp: Optional[datetime] = None,
) -> Path:
    """Write a snapshot to ``path``, never downgrading an existing one.

    Args:
        path: Target snapshot file, e.g. ``data/gpu_pccg_23_August_2026.json``.
        data: Snapshot envelope, normally from `build_snapshot`.
        timestamp: Clock for the sidecar filename; injectable for tests.

    Returns:
        The path actually written — ``path`` itself, or the ``.partial-*``
        sidecar when the incoming snapshot held fewer products than the one
        already on disk.
    """
    incoming = snapshot_size(data)
    existing = read_snapshot(path)

    if existing is not None:
        current = snapshot_size(existing)
        if incoming < current:
            stamp = (timestamp or datetime.now()).strftime("%H%M%S")
            sidecar = path.with_name(f"{path.stem}.partial-{stamp}{path.suffix}")
            _atomic_write(sidecar, data)
            LOGGER.warning(
                "Refusing to overwrite %s: on-disk snapshot has %d products, "
                "this run matched only %d. Parked the weaker result at %s.",
                path.name, current, incoming, sidecar.name,
            )
            return sidecar

    _atomic_write(path, data)
    LOGGER.info("Saved: %s (%d products)", path, incoming)
    return path


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
