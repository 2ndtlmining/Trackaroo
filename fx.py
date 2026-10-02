"""Daily AUD/USD rate cache (#32).

Fetches the RBA F11.1 table (column FXRUSD = USD per AUD) once a day, falling
back to Frankfurter, and upserts into ``fx_rates`` as ``aud_per_usd``. Best
effort: the web dashboard only needs a recent rate to convert US launch MSRPs.
"""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from config import DB_PATH
from migrate import migrate_add_fx_rates_table

LOGGER = logging.getLogger(__name__)

RBA_URL = "https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv"
FRANKFURTER_URL = "https://api.frankfurter.app/latest?from=USD&to=AUD"
HEADERS = {"User-Agent": "Trackaroo/1.0 (+https://github.com/2ndtlmining/Trackaroo)"}
TIMEOUT = 10
MIN_AUD_PER_USD = 1.0
MAX_AUD_PER_USD = 2.5
BACKFILL_DAYS = 7  # the RBA path also fills recent missing days (controller ruling R1)


def _in_bounds(rate: float, source: str = "") -> bool:
    ok = MIN_AUD_PER_USD <= rate <= MAX_AUD_PER_USD
    if not ok:
        LOGGER.warning(
            "FX %s rate %.4f outside %.1f-%.1f, rejected", source, rate, MIN_AUD_PER_USD, MAX_AUD_PER_USD
        )
    return ok


def _numeric_rba_rows(text: str) -> List[Tuple[str, float]]:
    """Every dated row with a numeric FXRUSD value as (YYYY-MM-DD, usd_per_aud), file order."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    col = None
    start = 0
    for i, row in enumerate(rows):
        if row and row[0].strip().lower() == "series id":
            for j, cell in enumerate(row):
                if cell.strip() == "FXRUSD":
                    col = j
            start = i + 1
            break
    if col is None:
        return []
    out: List[Tuple[str, float]] = []
    for row in rows[start:]:
        if not row or len(row) <= col:
            continue
        try:
            d = datetime.strptime(row[0].strip(), "%d-%b-%Y").date()
            v = float(row[col].strip())
        except ValueError:
            continue
        if v > 0:
            out.append((d.isoformat(), v))
    return out


def parse_rba_rows(text: str) -> List[Tuple[str, float]]:
    """Every in-bounds (YYYY-MM-DD, aud_per_usd) row of the RBA table, oldest first."""
    rows = []
    for d, v in _numeric_rba_rows(text):
        rate = 1.0 / v
        if _in_bounds(rate, "RBA"):
            rows.append((d, rate))
    return sorted(rows)


def parse_rba_csv(text: str) -> Optional[Tuple[str, float]]:
    """Latest numeric FXRUSD row as (YYYY-MM-DD, aud_per_usd); None if absent or out of bounds."""
    rows = _numeric_rba_rows(text)
    if not rows:
        return None
    d, v = max(rows)
    rate = 1.0 / v
    return (d, rate) if _in_bounds(rate, "RBA") else None


def parse_frankfurter(payload: dict) -> Optional[Tuple[str, float]]:
    try:
        d = date.fromisoformat(str(payload["date"])).isoformat()
        rate = float(payload["rates"]["AUD"])
    except (KeyError, TypeError, ValueError):
        return None
    return (d, rate) if _in_bounds(rate, "Frankfurter") else None


def _fetch_rba() -> List[Tuple[str, float]]:
    resp = requests.get(RBA_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    latest = parse_rba_csv(resp.text)
    if latest is None:
        return []
    cutoff = (date.fromisoformat(latest[0]) - timedelta(days=BACKFILL_DAYS)).isoformat()
    return [r for r in parse_rba_rows(resp.text) if r[0] >= cutoff]


def _fetch_frankfurter() -> List[Tuple[str, float]]:
    resp = requests.get(FRANKFURTER_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    row = parse_frankfurter(resp.json())
    return [row] if row else []


def run(db_path: Optional[Path] = None) -> Optional[Tuple[str, float, str]]:
    """Fetch and cache the rate. Returns (date, aud_per_usd, source) for the newest row, or None."""
    db_path = Path(db_path) if db_path is not None else DB_PATH
    rows: List[Tuple[str, float]] = []
    source = ""
    for name, fetch in (("rba", _fetch_rba), ("frankfurter", _fetch_frankfurter)):
        try:
            rows = fetch()
        except Exception as e:  # noqa: BLE001 - any source failure falls through
            LOGGER.warning("FX source %s failed: %s", name, e)
            rows = []
        if rows:
            source = name
            break
    if not rows:
        LOGGER.warning("FX rate not updated: no AUD/USD source available")
        return None

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(str(db_path))
    try:
        migrate_add_fx_rates_table(conn)
        conn.executemany(
            "INSERT INTO fx_rates (rate_date, aud_per_usd, source, fetched_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(rate_date) DO UPDATE SET aud_per_usd = excluded.aud_per_usd,"
            " source = excluded.source, fetched_at = excluded.fetched_at",
            [(d, r, source, fetched_at) for d, r in rows],
        )
        conn.commit()
    finally:
        conn.close()
    d, r = max(rows)
    LOGGER.info("FX rate %s: %.4f AUD per USD (%s, %d row(s))", d, r, source, len(rows))
    return (d, r, source)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
