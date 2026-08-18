"""
Backfill launch_msrp_usd from a curated model -> USD mapping.

None of the three spec sources (rightnow-gpu-db, intel-processors-csv,
amd-com) publish launch pricing in their payloads, so the specs table's
launch_msrp_usd column is NULL for every row. This script applies the curated
map in db/launch_msrp.json (keyed by products.model) to the specs table.

Idempotent: a row is only written when its launch_msrp_usd differs from the
mapping, and sync_specs.py never overwrites the column (it only INSERTs fresh
rows, refreshes last_synced_at, and backfills the TechPowerUp-grade extra
columns), so a one-time backfill survives the weekly re-sync.

Usage:
    python backfill_msrp.py [--dry-run] [--json PATH]
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from config import BASE_DIR, DB_PATH

LOGGER = logging.getLogger("backfill_msrp")

# Curated mapping shipped with the repo (also baked into the Docker image via
# `COPY db/ db/`); see db/launch_msrp.json.
DEFAULT_MAPPING = BASE_DIR / "db" / "launch_msrp.json"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = DB_PATH
    if not db_path.exists():
        LOGGER.error("Database not found at %s. Run seed.py first.", db_path)
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def load_mapping(path: Path) -> Dict[str, float]:
    """Load + validate the model -> USD JSON map. Raises ValueError on bad input."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("mapping must be a JSON object of model -> USD")
    mapping: Dict[str, float] = {}
    for model, price in data.items():
        if not isinstance(price, (int, float)) or price <= 0:
            raise ValueError(f"invalid MSRP for {model!r}: {price!r}")
        mapping[str(model)] = float(price)
    return mapping


def apply_mapping(
    conn: sqlite3.Connection,
    mapping: Dict[str, float],
    dry_run: bool = False,
) -> Tuple[int, Set[str], Set[str]]:
    """Set launch_msrp_usd on spec rows whose product matches a mapping key.

    Returns (updated, unmatched, unset) where `unmatched` is the set of mapping
    keys with no matching product and `unset` is the set of product models that
    still have a NULL launch_msrp_usd afterwards (no mapping entry). Idempotent:
    rows already equal to the mapped price are left untouched.
    """
    updated = 0
    unmatched: Set[str] = set(mapping)
    for model, price in mapping.items():
        product_rows: List[sqlite3.Row] = conn.execute(
            "SELECT id FROM products WHERE model = ?", (model,)
        ).fetchall()
        if not product_rows:
            continue
        unmatched.discard(model)
        for prow in product_rows:
            row = conn.execute(
                "SELECT spec_id, launch_msrp_usd FROM specs WHERE product_id = ?",
                (prow["id"],),
            ).fetchone()
            if row is None:
                continue
            if row["launch_msrp_usd"] != price:
                if not dry_run:
                    conn.execute(
                        "UPDATE specs SET launch_msrp_usd = ? WHERE spec_id = ?",
                        (price, row["spec_id"]),
                    )
                updated += 1
    if not dry_run:
        conn.commit()

    unset = {
        r["model"]
        for r in conn.execute(
            """SELECT p.model FROM products p
               JOIN specs s ON s.product_id = p.id
               WHERE s.launch_msrp_usd IS NULL"""
        ).fetchall()
    }
    return updated, unmatched, unset


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Backfill launch MSRPs into the specs table"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="path to the model->USD mapping "
                             "(default: db/launch_msrp.json)")
    args = parser.parse_args(argv)

    path = Path(args.json_path) if args.json_path else DEFAULT_MAPPING
    if not path.exists():
        LOGGER.error("Mapping file not found at %s", path)
        sys.exit(1)
    try:
        mapping = load_mapping(path)
    except (json.JSONDecodeError, ValueError) as e:
        LOGGER.error("Invalid mapping file: %s", e)
        sys.exit(1)

    conn = get_connection()
    try:
        updated, unmatched, unset = apply_mapping(conn, mapping, dry_run=args.dry_run)
    finally:
        conn.close()

    prefix = "DRY-RUN: " if args.dry_run else ""
    LOGGER.info("%slaunch_msrp_usd set for %d spec row(s)", prefix, updated)
    if unmatched:
        LOGGER.warning("No product matches for: %s", ", ".join(sorted(unmatched)))
    if unset:
        LOGGER.info("Products still missing MSRP: %s", ", ".join(sorted(unset)))


if __name__ == "__main__":
    main()