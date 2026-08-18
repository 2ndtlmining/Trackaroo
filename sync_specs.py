"""
Sync external spec data into the specs table.

Weekly, best-effort companion to the daily price pipeline (run_daily.py).
Fetches the approved spec sources, matches them against the products table,
and upserts into the specs table. Rows are never deleted: a product whose
upstream record disappears keeps its last-known row.

Sources (see IMPROVEMENT_16_Aug_V1.md §3):
- GPU:  RightNow-AI/RightNow-GPU-Database (Apache-2.0)
- Intel: toUpperCase78/intel-processors CSVs (GPL-3.0)
- AMD:  first-party amd.com product pages

Usage:
    python sync_specs.py                 # full sync: fetch + match + write
    python sync_specs.py --category gpu  # GPU only
    python sync_specs.py --category cpu  # CPU only (Intel + AMD sources)
    python sync_specs.py --dry-run       # fetch + match + report, no DB writes
    python sync_specs.py --report-only   # print last sync's report, no fetch
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from config import (
    AMD_FETCH_DELAY_SECONDS,
    DATA_DIR,
    DB_PATH,
    SPEC_FETCH_TIMEOUT_SECONDS,
    SPEC_RETRY_BACKOFF,
)
from spec_matching import match_cpu, match_gpu

LOGGER = logging.getLogger(__name__)

# ── Sources ───────────────────────────────────────────────────────────
SOURCE_GPU = "rightnow-gpu-db"
SOURCE_INTEL = "intel-processors-csv"
SOURCE_AMD = "amd-com"

GPU_SOURCE_URL = (
    "https://raw.githubusercontent.com/RightNow-AI/RightNow-GPU-Database/"
    "main/data/all-gpus.json"
)
INTEL_SOURCE_URLS = [
    "https://raw.githubusercontent.com/toUpperCase78/intel-processors/master/"
    "intel_core_processors_v1_8.csv",
    "https://raw.githubusercontent.com/toUpperCase78/intel-processors/master/"
    "Intel_Core_Ultra_Processors_v1_10.csv",
]
AMD_BASE_URL = "https://www.amd.com/en/products/processors/desktops/ryzen"
# amd.com blocks the default python-requests UA; a browser UA is required.
AMD_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

REPORT_FILENAME = "spec_sync_report.json"


class SourceFetchError(Exception):
    """A spec source could not be fetched or parsed (source-level failure)."""


# ── HTTP ──────────────────────────────────────────────────────────────
def fetch_url(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    retries: int = 2,
    timeout: int = SPEC_FETCH_TIMEOUT_SECONDS,
) -> Optional[str]:
    """Fetch a URL, returning the body decoded as UTF-8, or None on failure.

    4xx responses are definitive (not retried); 5xx and network errors are
    retried with a short fixed backoff.
    """
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=headers or {}, timeout=timeout)
        except requests.RequestException as e:
            LOGGER.warning("Attempt %d failed for %s: %s", attempt + 1, url, e)
            time.sleep(SPEC_RETRY_BACKOFF)
            continue
        if r.status_code == 200:
            return r.content.decode("utf-8", errors="replace")
        if 400 <= r.status_code < 500:
            LOGGER.warning("Definitive HTTP %s for %s", r.status_code, url)
            return None
        LOGGER.warning("Non-200 status %s for %s", r.status_code, url)
        time.sleep(SPEC_RETRY_BACKOFF)
    return None


# ── Value helpers ─────────────────────────────────────────────────────
def _clean(value: Optional[str]) -> Optional[str]:
    """Trim whitespace; empty/None becomes None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ghz_to_mhz(value: Optional[str]) -> Optional[int]:
    """Extract a GHz figure ('4.60', '4.3 GHz', 'Up to 5.7 GHz') → MHz int."""
    if not value:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", value)
    if not m:
        return None
    return int(round(float(m.group(1)) * 1000))


def _strip_unit(value: Optional[str], unit: str) -> Optional[str]:
    """Drop a trailing unit ('170W' → '170', '128 MB' → '128')."""
    if not value:
        return None
    v = value.strip()
    if unit and v.upper().endswith(unit.upper()):
        v = v[: -len(unit)].strip()
    return v or None


def _sanitize_name(name: str) -> str:
    """Drop C1 control chars (U+0080–U+009F) from a source name.

    Defensive guard against charset mis-decoding (e.g. UTF-8 bytes read as
    latin-1 produce C1 control chars); legitimate product names never
    contain them.
    """
    return "".join(ch for ch in name if not 0x80 <= ord(ch) <= 0x9F)


def _amd_launch_date_to_iso(value: Optional[str]) -> Optional[str]:
    """Convert amd.com 'MM/DD/YYYY' launch dates to ISO; None if unparseable."""
    if not value:
        return None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value.strip())
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _amd_memory_speed_mhz(value: Optional[str]) -> Optional[int]:
    """Parse amd.com 'Max Memory Speed' ('2x1R DDR5-5600 2x2R DDR5-5600 …')
    into the highest supported data rate in MHz (e.g. 5600)."""
    if not value:
        return None
    speeds = [int(m) for m in re.findall(r"\b(\d{3,5})\s*MT/s\b", value)]
    if not speeds:
        speeds = [int(m) for m in re.findall(r"[- ](\d{3,5})\b", value)]
    return max(speeds) if speeds else None


def _clean_codename(value: Optional[str]) -> Optional[str]:
    """Trim a CPU codename and drop the trailing socket tag amd.com appends
    ('Granite Ridge AM5' → 'Granite Ridge')."""
    name = _clean(value)
    if name is None:
        return None
    return re.sub(r"\s+AM[45]\s*$", "", name) or None


# ── Parsers (pure functions: text in → normalized records out) ───────
def parse_gpu_records(json_text: str) -> List[Dict[str, Any]]:
    """Parse the RightNow GPU dataset JSON into normalized records.

    Raises SourceFetchError if the payload is not a list of named records.
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise SourceFetchError(f"GPU source: malformed JSON ({e})") from e
    if not isinstance(data, list):
        raise SourceFetchError("GPU source: expected a JSON list of records")

    records: List[Dict[str, Any]] = []
    for g in data:
        if not isinstance(g, dict) or not g.get("name"):
            continue
        records.append({
            "name": g["name"],
            "raw": g,
            "category": "gpu",
            "architecture": g.get("architecture"),
            "generation": g.get("generation"),
            "launch_date": g.get("releaseDate"),
            "launch_msrp_usd": None,
            "vram_gb": _to_float(g.get("memorySize")),
            "memory_bus_width_bit": _to_int(g.get("memoryBus")),
            "memory_type": g.get("memoryType"),
            "tdp_watts": _to_int(g.get("tdp")),
            "core_count": _to_int(g.get("shaders")),
            "thread_count": None,
            "base_clock_mhz": _to_int(g.get("baseClock")),
            "boost_clock_mhz": _to_int(g.get("boostClock")),
            "socket": None,
            "cache_l3_mb": None,
            # TechPowerUp-grade detail (see backfill_specs_extra)
            "gpu_die": _clean(g.get("gpuName")),
            "bus_interface": _clean(g.get("busInterface")),
            "memory_bandwidth_gbps": _to_float(g.get("memoryBandwidth")),
            "memory_clock_mhz": _to_float(g.get("memoryClock")),
            "process_nm": _to_float(g.get("processSize")),
            "foundry": _clean(g.get("foundry")),
            "codename": None,
            "l1_cache_kb": None,
            # l2Cache is the GPU's L2 (e.g. 96 MB on RTX 5090), not CPU L3
            "l2_cache_mb": _to_float(g.get("l2Cache")),
            "memory_speed_mhz": None,
            "memory_channels": None,
            "memory_types": None,
            "integrated_graphics": None,
        })
    return records


def parse_intel_records(csv_texts: List[str]) -> List[Dict[str, Any]]:
    """Parse the Intel CSV payloads (one text per file) into records.

    Raises SourceFetchError if a payload is empty or has no data rows.
    """
    records: List[Dict[str, Any]] = []
    for text in csv_texts:
        if not text.strip():
            raise SourceFetchError("Intel source: empty CSV response")
        rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
        if not rows:
            raise SourceFetchError("Intel source: CSV has no data rows")
        for row in rows:
            name = _clean(row.get("Product"))
            if not name:
                continue
            records.append({
                "name": name,
                "raw": row,
                "category": "cpu",
                "architecture": _clean(row.get("Code Name")),
                "generation": None,
                # 'Q1'23' style — stored verbatim (meaningful, column is TEXT)
                "launch_date": _clean(row.get("Release Date")),
                "launch_msrp_usd": None,
                "vram_gb": None,
                "memory_bus_width_bit": None,
                "memory_type": None,
                "tdp_watts": _to_int(_clean(row.get("TDP(W)"))),
                "core_count": _to_int(_clean(row.get("Cores"))),
                "thread_count": _to_int(_clean(row.get("Threads"))),
                "base_clock_mhz": _ghz_to_mhz(_clean(row.get("Base Freq.(GHz)"))),
                "boost_clock_mhz": _ghz_to_mhz(_clean(row.get("Max. Turbo Freq.(GHz)"))),
                # v1_8 has no socket column; Ultra has 'Sockets Supported'
                "socket": _clean(row.get("Sockets Supported")),
                # Intel's 'Cache(MB)' is 'Intel Smart Cache' (total cache) —
                # for the desktop watchlist it equals TPU's L3 figure.
                "cache_l3_mb": _to_float(_clean(row.get("Cache(MB)"))),
                # TechPowerUp-grade detail (see backfill_specs_extra)
                "gpu_die": None,
                "bus_interface": None,
                "memory_bandwidth_gbps": None,
                "memory_clock_mhz": None,
                "process_nm": _to_float(_clean(row.get("Lithography(nm)"))),
                "foundry": None,
                "codename": _clean(row.get("Code Name")),
                "l1_cache_kb": None,
                "l2_cache_mb": None,
                "memory_speed_mhz": _to_int(_clean(row.get("Max Memory Speed(MHz)"))),
                "memory_channels": _to_int(_clean(row.get("Max Memory Channels"))),
                "memory_types": _clean(row.get("Memory Types")),
                "integrated_graphics": _clean(row.get("Integrated Graphics")),
            })
    return records


def parse_amd_record(html: str) -> Optional[Dict[str, Any]]:
    """Parse one amd.com product page (dt/dd spec table) into a record.

    Returns None when the spec table (or its Name field) is not found.
    """
    soup = BeautifulSoup(html, "html.parser")
    fields: Dict[str, str] = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        key = " ".join(dt.get_text(" ", strip=True).split())
        if not key:
            continue
        value = " ".join(dd.get_text(" ", strip=True).split()) if dd is not None else ""
        fields[key] = value

    name = _clean(_sanitize_name(fields.get("Name") or ""))
    if not name:
        return None
    return {
        "name": name,
        "raw": fields,
        "category": "cpu",
        "architecture": _clean(fields.get("Processor Architecture")),
        "generation": _clean(fields.get("Series")),
        "launch_date": _amd_launch_date_to_iso(fields.get("Launch Date")),
        "launch_msrp_usd": None,
        "vram_gb": None,
        "memory_bus_width_bit": None,
        "memory_type": None,
        "tdp_watts": _to_int(_strip_unit(fields.get("Default TDP"), "W")),
        "core_count": _to_int(fields.get("# of CPU Cores")),
        "thread_count": _to_int(fields.get("# of Threads")),
        "base_clock_mhz": _ghz_to_mhz(_strip_unit(fields.get("Base Clock"), "GHz")),
        "boost_clock_mhz": _ghz_to_mhz(_strip_unit(fields.get("Max. Boost Clock"), "GHz")),
        "socket": _clean(fields.get("CPU Socket")),
        "cache_l3_mb": _to_float(_strip_unit(fields.get("L3 Cache"), "MB")),
        # TechPowerUp-grade detail (see backfill_specs_extra)
        "gpu_die": None,
        "bus_interface": None,
        "memory_bandwidth_gbps": None,
        "memory_clock_mhz": None,
        "process_nm": None,
        "foundry": None,
        "codename": _clean_codename(fields.get("Former Codename")),
        "l1_cache_kb": _to_float(_strip_unit(fields.get("L1 Cache"), "KB")),
        "l2_cache_mb": _to_float(_strip_unit(fields.get("L2 Cache"), "MB")),
        "memory_speed_mhz": _amd_memory_speed_mhz(fields.get("Max Memory Speed")),
        "memory_channels": _to_int(fields.get("Memory Channels")),
        "memory_types": _clean(fields.get("System Memory Type")),
        "integrated_graphics": _clean(fields.get("Graphics Model")),
    }


def amd_series_for(model: str) -> Optional[str]:
    """Map an AMD model to its amd.com series path segment (e.g. '9000-series')."""
    m = re.search(r"(\d{4})", model)
    if not m:
        return None
    first = m.group(1)[0]
    if first in "5789":
        return f"{first}000-series"
    return None


def amd_url_for(model: str) -> Optional[str]:
    """Build the amd.com product-page URL for a Ryzen desktop model."""
    series = amd_series_for(model)
    if not series:
        return None
    slug = "amd-" + model.strip().lower().replace(" ", "-")
    return f"{AMD_BASE_URL}/{series}/{slug}.html"


# ── Fetchers ──────────────────────────────────────────────────────────
def fetch_gpu_records() -> List[Dict[str, Any]]:
    """Fetch + parse the GPU dataset. Raises SourceFetchError on failure."""
    text = fetch_url(GPU_SOURCE_URL)
    if text is None:
        raise SourceFetchError(f"GPU source unreachable: {GPU_SOURCE_URL}")
    records = parse_gpu_records(text)
    if not records:
        raise SourceFetchError("GPU source returned no records")
    return records


def fetch_intel_records() -> List[Dict[str, Any]]:
    """Fetch + parse both Intel CSVs. Raises SourceFetchError on failure."""
    texts: List[str] = []
    for url in INTEL_SOURCE_URLS:
        text = fetch_url(url)
        if text is None:
            raise SourceFetchError(f"Intel source unreachable: {url}")
        texts.append(text)
    records = parse_intel_records(texts)
    if not records:
        raise SourceFetchError("Intel source returned no records")
    return records


def fetch_amd_records(
    models: List[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Fetch + parse amd.com pages for each model.

    Per-SKU failures (404 for OEM-only parts, network errors) are reported,
    not source-level failures. Returns (records, fetch_failed).
    """
    records: List[Dict[str, Any]] = []
    failed: List[Dict[str, str]] = []
    for i, model in enumerate(models):
        url = amd_url_for(model)
        if url is None:
            failed.append({"model": model, "reason": "no amd.com URL (unrecognised series)"})
            continue
        if i:
            time.sleep(AMD_FETCH_DELAY_SECONDS)
        html = fetch_url(url, headers=AMD_UA, retries=0)
        if html is None:
            failed.append({"model": model, "reason": "fetch failed"})
            continue
        rec = parse_amd_record(html)
        if rec is None:
            failed.append({"model": model, "reason": "page fetched but spec table not found"})
            continue
        records.append(rec)
    return records, failed


# ── DB ────────────────────────────────────────────────────────────────
def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get a database connection (foreign keys on, WAL, rows by name).

    db_path defaults to config.DB_PATH, resolved at call time (not import
    time) so tests can monkeypatch the module global.
    """
    if db_path is None:
        db_path = DB_PATH
    if not db_path.exists():
        LOGGER.error("Database not found at %s. Run seed.py first.", db_path)
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _specs_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'specs'"
    ).fetchone()
    return row is not None


def load_products(conn: sqlite3.Connection, category: Optional[str] = None) -> List[sqlite3.Row]:
    """Load products (tracked and untracked — spec data for historical
    products is still valid to have)."""
    sql = "SELECT id, category, brand, model, vram_gb FROM products"
    params: Tuple = ()
    if category:
        sql += " WHERE category = ?"
        params = (category,)
    return conn.execute(sql, params).fetchall()


_INSERT_SQL = """
INSERT INTO specs (
    product_id, source, source_record_key, category,
    architecture, generation, launch_date, launch_msrp_usd,
    vram_gb, memory_bus_width_bit, memory_type, tdp_watts, core_count,
    thread_count, base_clock_mhz, boost_clock_mhz, socket, cache_l3_mb,
    gpu_die, bus_interface, memory_bandwidth_gbps, memory_clock_mhz,
    process_nm, foundry, codename, l1_cache_kb, l2_cache_mb,
    memory_speed_mhz, memory_channels, memory_types, integrated_graphics,
    raw_json, last_synced_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _record_values(product_id: int, source: str, rec: Dict[str, Any], raw_json: str, now: str):
    return (
        product_id, source, rec["name"], rec["category"],
        rec["architecture"], rec["generation"], rec["launch_date"], rec["launch_msrp_usd"],
        rec["vram_gb"], rec["memory_bus_width_bit"], rec["memory_type"],
        rec["tdp_watts"], rec["core_count"], rec["thread_count"],
        rec["base_clock_mhz"], rec["boost_clock_mhz"], rec["socket"],
        rec["cache_l3_mb"],
        rec["gpu_die"], rec["bus_interface"], rec["memory_bandwidth_gbps"],
        rec["memory_clock_mhz"], rec["process_nm"], rec["foundry"],
        rec["codename"], rec["l1_cache_kb"], rec["l2_cache_mb"],
        rec["memory_speed_mhz"], rec["memory_channels"], rec["memory_types"],
        rec["integrated_graphics"],
        raw_json, now,
    )


# Column set for seed export/import — mirrors _INSERT_SQL (all specs columns
# except the autoincrement spec_id, which is reassigned on import).
_SEED_COLUMNS = [
    "product_id", "source", "source_record_key", "category",
    "architecture", "generation", "launch_date", "launch_msrp_usd",
    "vram_gb", "memory_bus_width_bit", "memory_type", "tdp_watts", "core_count",
    "thread_count", "base_clock_mhz", "boost_clock_mhz", "socket", "cache_l3_mb",
    "gpu_die", "bus_interface", "memory_bandwidth_gbps", "memory_clock_mhz",
    "process_nm", "foundry", "codename", "l1_cache_kb", "l2_cache_mb",
    "memory_speed_mhz", "memory_channels", "memory_types", "integrated_graphics",
    "raw_json", "last_synced_at",
]


def export_specs(conn: sqlite3.Connection, path: Path) -> int:
    """Write the specs table as JSON seed data (baked into the Docker image so
    a fresh volume has spec rows immediately — see bootstrap-data.sh).

    Excludes spec_id (auto-assigned on import). Values keep their SQLite types
    (numbers/strings), raw_json stays a JSON string.
    """
    rows = conn.execute(
        f"SELECT {', '.join(_SEED_COLUMNS)} FROM specs ORDER BY product_id, source"
    ).fetchall()
    data = [dict(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(data)


def import_specs(conn: sqlite3.Connection, path: Path, dry_run: bool = False) -> int:
    """Upsert specs rows from a JSON seed export.

    INSERT OR REPLACE keys on the UNIQUE (product_id, source) constraint, so a
    re-run on an already-hydrated DB is a safe no-op. Returns rows imported.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("seed spec file must contain a JSON list of rows")
    sql = _INSERT_SQL.replace("INSERT INTO specs", "INSERT OR REPLACE INTO specs", 1)
    for rec in data:
        values = tuple(rec.get(col) for col in _SEED_COLUMNS)
        if not dry_run:
            conn.execute(sql, values)
    if not dry_run:
        conn.commit()
    return len(data)


_EXTRA_COLUMNS = [
    "gpu_die",
    "bus_interface",
    "memory_bandwidth_gbps",
    "memory_clock_mhz",
    "process_nm",
    "foundry",
    "codename",
    "l1_cache_kb",
    "l2_cache_mb",
    "memory_speed_mhz",
    "memory_channels",
    "memory_types",
    "integrated_graphics",
]


def _extract_extra(raw: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Extract TechPowerUp-grade fields from a verbatim source record.

    Each parser also emits these fields up front (for fresh rows); this
    function re-derives them from raw_json so existing rows can be backfilled
    without a re-fetch. Unknown keys yield None (never an exception).
    """
    if source == SOURCE_GPU:
        return {
            "gpu_die": _clean(raw.get("gpuName")),
            "bus_interface": _clean(raw.get("busInterface")),
            "memory_bandwidth_gbps": _to_float(raw.get("memoryBandwidth")),
            "memory_clock_mhz": _to_float(raw.get("memoryClock")),
            "process_nm": _to_float(raw.get("processSize")),
            "foundry": _clean(raw.get("foundry")),
            "codename": None,
            "l1_cache_kb": None,
            "l2_cache_mb": _to_float(raw.get("l2Cache")),
            "memory_speed_mhz": None,
            "memory_channels": None,
            "memory_types": None,
            "integrated_graphics": None,
        }
    if source == SOURCE_INTEL:
        return {
            "gpu_die": None,
            "bus_interface": None,
            "memory_bandwidth_gbps": None,
            "memory_clock_mhz": None,
            "process_nm": _to_float(_clean(raw.get("Lithography(nm)"))),
            "foundry": None,
            "codename": _clean(raw.get("Code Name")),
            "l1_cache_kb": None,
            "l2_cache_mb": None,
            "memory_speed_mhz": _to_int(_clean(raw.get("Max Memory Speed(MHz)"))),
            "memory_channels": _to_int(_clean(raw.get("Max Memory Channels"))),
            "memory_types": _clean(raw.get("Memory Types")),
            "integrated_graphics": _clean(raw.get("Integrated Graphics")),
        }
    if source == SOURCE_AMD:
        return {
            "gpu_die": None,
            "bus_interface": None,
            "memory_bandwidth_gbps": None,
            "memory_clock_mhz": None,
            "process_nm": None,
            "foundry": None,
            "codename": _clean_codename(raw.get("Former Codename")),
            "l1_cache_kb": _to_float(_strip_unit(raw.get("L1 Cache"), "KB")),
            "l2_cache_mb": _to_float(_strip_unit(raw.get("L2 Cache"), "MB")),
            "memory_speed_mhz": _amd_memory_speed_mhz(raw.get("Max Memory Speed")),
            "memory_channels": _to_int(raw.get("Memory Channels")),
            "memory_types": _clean(raw.get("System Memory Type")),
            "integrated_graphics": _clean(raw.get("Graphics Model")),
        }
    return {col: None for col in _EXTRA_COLUMNS}


def backfill_specs_extra(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """Fill the TechPowerUp-grade columns from each row's verbatim raw_json.

    Idempotent: only rows where a target column is NULL are touched, so it is
    safe to run after every sync. Intel 'Cache(MB)' is also mapped into
    cache_l3_mb here (it matches TPU's L3 for the desktop watchlist).
    Returns the number of rows updated.
    """
    updated = 0
    if not _specs_table_exists(conn):
        return 0
    existing = {
        r["name"] for r in conn.execute("PRAGMA table_info(specs)").fetchall()
    }
    if not set(_EXTRA_COLUMNS).issubset(existing):
        LOGGER.warning(
            "specs table is missing extra columns (run `python migrate.py` "
            "first); skipping backfill"
        )
        return 0
    rows = conn.execute(
        f"SELECT spec_id, source, raw_json, cache_l3_mb, "
        f"{', '.join(_EXTRA_COLUMNS)} FROM specs"
    ).fetchall()
    for row in rows:
        try:
            raw = json.loads(row["raw_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(raw, dict):
            continue
        extra = _extract_extra(raw, row["source"])
        sets = [
            f"{col} = ?"
            for col in _EXTRA_COLUMNS
            if row[col] is None and extra.get(col) is not None
        ]
        params = [extra[col] for col in _EXTRA_COLUMNS if row[col] is None and extra.get(col) is not None]
        if row["cache_l3_mb"] is None and row["source"] == SOURCE_INTEL:
            cache_mb = _to_float(_clean(raw.get("Cache(MB)")))
            if cache_mb is not None:
                sets.append("cache_l3_mb = ?")
                params.append(cache_mb)
        if not sets:
            continue
        if not dry_run:
            conn.execute(
                f"UPDATE specs SET {', '.join(sets)} WHERE spec_id = ?",
                (*params, row["spec_id"]),
            )
        updated += 1
    if not dry_run:
        conn.commit()
    return updated


def sync_source(
    category: str,
    source: str,
    records: List[Dict[str, Any]],
    conn: sqlite3.Connection,
    products: List[sqlite3.Row],
    dry_run: bool = False,
    fetch_failed: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Match source records against products and upsert specs rows.

    Rules (IMPROVEMENT_16 §5.3):
    - No match → unmatched report, no row written.
    - Match, no existing row → insert.
    - Match, existing row with identical raw_json → refresh last_synced_at.
    - Match, existing row with different raw_json → conflict, NOT overwritten.
    - Existing row whose product no longer matches → left untouched.
    Rows are never deleted.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats: Dict[str, Any] = {
        "source": source,
        "category": category,
        "records_fetched": len(records),
        "matched_new": 0,
        "matched_unchanged": 0,
        "conflicts": [],
        "unmatched_products": [],
        "fetch_failed": fetch_failed or [],
    }

    for product in products:
        if category == "gpu":
            rec = match_gpu(product["model"], product["vram_gb"], records)
        else:
            rec = match_cpu(product["model"], records)
        if rec is None:
            stats["unmatched_products"].append(
                {"product_id": product["id"], "model": product["model"]}
            )
            continue

        raw_json = json.dumps(rec["raw"], sort_keys=True, ensure_ascii=False)
        row = conn.execute(
            "SELECT spec_id, raw_json FROM specs WHERE product_id = ? AND source = ?",
            (product["id"], source),
        ).fetchone()

        if row is None:
            if not dry_run:
                conn.execute(_INSERT_SQL, _record_values(product["id"], source, rec, raw_json, now))
            stats["matched_new"] += 1
        elif row["raw_json"] == raw_json:
            if not dry_run:
                conn.execute(
                    "UPDATE specs SET last_synced_at = ? WHERE spec_id = ?",
                    (now, row["spec_id"]),
                )
            stats["matched_unchanged"] += 1
        else:
            stats["conflicts"].append({
                "product_id": product["id"],
                "model": product["model"],
                "source_record_key": rec["name"],
            })

    if not dry_run:
        conn.commit()
    return stats


# ── Report ────────────────────────────────────────────────────────────
def build_report(
    synced_at: str,
    dry_run: bool,
    source_stats: List[Dict[str, Any]],
    failed_sources: List[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "synced_at": synced_at,
        "dry_run": dry_run,
        "sources": {s["source"]: s for s in source_stats},
        "failed_sources": failed_sources,
        "summary": {
            "matched_new": sum(s["matched_new"] for s in source_stats),
            "matched_unchanged": sum(s["matched_unchanged"] for s in source_stats),
            "conflicts": sum(len(s["conflicts"]) for s in source_stats),
            "unmatched": sum(len(s["unmatched_products"]) for s in source_stats),
        },
    }


def write_report(report: Dict[str, Any], data_dir: Optional[Path] = None) -> Path:
    data_dir = data_dir or DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / REPORT_FILENAME
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_report(data_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = (data_dir or DATA_DIR) / REPORT_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ── Orchestration ─────────────────────────────────────────────────────
def _run_record_source(
    conn: sqlite3.Connection,
    products: List[sqlite3.Row],
    fetch_fn,
    source: str,
    category: str,
    dry_run: bool,
    failed_sources: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Fetch + sync one whole-file source (GPU / Intel). Returns stats, or
    None on source-level failure (recorded in failed_sources)."""
    try:
        records = fetch_fn()
    except SourceFetchError as e:
        LOGGER.error("Source %s failed: %s", source, e)
        failed_sources.append({"source": source, "reason": str(e)})
        return None
    return sync_source(category, source, records, conn, products, dry_run=dry_run)


def _run_amd_source(
    conn: sqlite3.Connection,
    products: List[sqlite3.Row],
    dry_run: bool,
    failed_sources: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Fetch + sync the AMD.com source. Per-SKU 404s are expected (OEM-only
    parts); a total fetch failure is a source-level failure."""
    models = [p["model"] for p in products]
    try:
        records, fetch_failed = fetch_amd_records(models)
    except SourceFetchError as e:
        LOGGER.error("Source %s failed: %s", SOURCE_AMD, e)
        failed_sources.append({"source": SOURCE_AMD, "reason": str(e)})
        return None
    if models and not records:
        LOGGER.error("Source %s failed: no amd.com pages could be fetched", SOURCE_AMD)
        failed_sources.append(
            {"source": SOURCE_AMD, "reason": "all amd.com SKU fetches failed"}
        )
        return None
    return sync_source(
        "cpu", SOURCE_AMD, records, conn, products,
        dry_run=dry_run, fetch_failed=fetch_failed,
    )


def _log_summary(source_stats: List[Dict[str, Any]], failed_sources: List[Dict[str, str]]) -> None:
    s = build_report("", False, source_stats, failed_sources)["summary"]
    LOGGER.info(
        "\n%s\nSpec sync summary: %d new, %d unchanged, %d conflicts, %d unmatched\n%s",
        "=" * 60, s["matched_new"], s["matched_unchanged"], s["conflicts"],
        s["unmatched"], "=" * 60,
    )
    for st in source_stats:
        LOGGER.info(
            "  %-20s records=%-5d new=%-3d unchanged=%-3d conflicts=%-2d unmatched=%-2d fetch_failed=%d",
            st["source"], st["records_fetched"], st["matched_new"],
            st["matched_unchanged"], len(st["conflicts"]),
            len(st["unmatched_products"]), len(st["fetch_failed"]),
        )
        for c in st["conflicts"]:
            LOGGER.warning("    CONFLICT %s (product %d) vs source record %r",
                           c["model"], c["product_id"], c["source_record_key"])
        for u in st["unmatched_products"]:
            LOGGER.info("    unmatched: %s (product %d)", u["model"], u["product_id"])
    for f in failed_sources:
        LOGGER.error("  FAILED %-20s %s", f["source"], f["reason"])


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Sync external spec data into the specs table"
    )
    parser.add_argument("--category", choices=["gpu", "cpu"], default=None,
                        help="Sync only one category (default: both)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch + match + report, no DB writes")
    parser.add_argument("--report-only", action="store_true",
                        help="Print the last sync report and exit (no fetch)")
    parser.add_argument("--export", metavar="PATH", default=None,
                        help="Export the specs table as JSON seed data and exit "
                             "(regenerate data/specs_seed.json after extractor changes)")
    parser.add_argument("--import", dest="import_path", metavar="PATH", default=None,
                        help="Upsert specs from a JSON seed export and exit (no fetch)")
    args = parser.parse_args(argv)

    if args.export and args.import_path:
        parser.error("--export and --import are mutually exclusive")

    if args.report_only:
        report = read_report()
        if report is None:
            LOGGER.error("No previous sync report at %s", DATA_DIR / REPORT_FILENAME)
            sys.exit(1)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    if args.export or args.import_path:
        if args.import_path and not Path(args.import_path).exists():
            LOGGER.error("Seed file not found at %s", args.import_path)
            sys.exit(1)
        if not DB_PATH.exists():
            LOGGER.error("Database not found at %s. Run seed.py first.", DB_PATH)
            sys.exit(1)
        conn = get_connection()
        try:
            if not _specs_table_exists(conn):
                LOGGER.error("specs table is missing. Run: python migrate.py")
                sys.exit(1)
            if args.export:
                n = export_specs(conn, Path(args.export))
                LOGGER.info("Exported %d spec rows to %s", n, args.export)
            else:
                n = import_specs(conn, Path(args.import_path), dry_run=args.dry_run)
                LOGGER.info("Imported %d spec rows from %s", n, args.import_path)
        finally:
            conn.close()
        return

    if not DB_PATH.exists():
        LOGGER.error("Database not found at %s. Run seed.py first.", DB_PATH)
        sys.exit(1)

    conn = get_connection()
    try:
        if not _specs_table_exists(conn):
            LOGGER.error("specs table is missing. Run: python migrate.py")
            sys.exit(1)

        synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        products = load_products(conn)
        source_stats: List[Dict[str, Any]] = []
        failed_sources: List[Dict[str, str]] = []

        if args.category in (None, "gpu"):
            stats = _run_record_source(
                conn, [p for p in products if p["category"] == "gpu"],
                fetch_gpu_records, SOURCE_GPU, "gpu", args.dry_run, failed_sources,
            )
            if stats:
                source_stats.append(stats)

        if args.category in (None, "cpu"):
            cpu_products = [p for p in products if p["category"] == "cpu"]
            stats = _run_record_source(
                conn, [p for p in cpu_products if p["brand"].lower() == "intel"],
                fetch_intel_records, SOURCE_INTEL, "cpu", args.dry_run, failed_sources,
            )
            if stats:
                source_stats.append(stats)
            stats = _run_amd_source(conn, [p for p in cpu_products if p["brand"].lower() == "amd"],
                                    args.dry_run, failed_sources)
            if stats:
                source_stats.append(stats)

        if args.dry_run:
            LOGGER.info("(Dry run complete — no DB writes, report not saved)")
        else:
            backfilled = backfill_specs_extra(conn)
            if backfilled:
                LOGGER.info("Backfilled TechPowerUp-grade columns for %d specs rows", backfilled)
            report = build_report(synced_at, False, source_stats, failed_sources)
            path = write_report(report)
            LOGGER.info("Report written to %s", path)

        _log_summary(source_stats, failed_sources)

        if failed_sources:
            sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
