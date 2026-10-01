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
