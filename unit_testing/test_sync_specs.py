"""
Tests for sync_specs — parsers, fetchers, upsert logic, and the main entry
point. All network access is mocked (no live GitHub/amd.com calls).

Covers (IMPROVEMENT_16 §6):
- Parsers map source payloads to the specs column set
- fetch_url retry semantics (4xx definitive, 5xx/network retried)
- sync_source: fresh insert, no-op re-sync, conflict detection, unmatched,
  dry-run no-writes, never-delete
- main: fresh sync, dry-run, partial-category failure isolation, report-only
"""
import json
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync_specs as ss

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


# ── Fixture payloads ──────────────────────────────────────────────────

GPU_JSON = json.dumps([
    {
        "name": "GeForce RTX 4070 SUPER", "architecture": "Ada Lovelace",
        "generation": "GeForce 40", "releaseDate": "2024-01-08",
        "baseClock": 1980.0, "boostClock": 2475.0, "memorySize": 12.0,
        "memoryType": "GDDR6X", "memoryBus": 192, "tdp": 220,
        "shaders": 7168, "l2Cache": 48.0, "gpuName": "AD103",
        "busInterface": "PCIe 4.0 x16", "memoryBandwidth": 504.2,
        "memoryClock": 1313.0, "processSize": 5, "foundry": "TSMC",
    },
    {
        "name": "GeForce RTX 4070", "architecture": "Ada Lovelace",
        "generation": "GeForce 40", "releaseDate": "2023-02-16",
        "baseClock": 1920.0, "boostClock": 2475.0, "memorySize": 12.0,
        "memoryType": "GDDR6X", "memoryBus": 192, "tdp": 200,
        "shaders": 5888, "l2Cache": 36.0,
    },
])

INTEL_CSV = (
    "Product,Status,Release Date,Code Name,Cores,Threads,Lithography(nm),"
    "Max. Turbo Freq.(GHz),Base Freq.(GHz),TDP(W),Cache(MB),Cache Info,"
    "Max Memory Size(GB),Memory Types,Max Memory Speed(MHz),Integrated Graphics\n"
    "Core i5-13400,Launched,Q1'23,Raptor Lake,10,16,7,4.60,2.50,148,20,"
    "Intel Smart Cache,192,Up to DDR5 4800 MT/s,N/A,Intel UHD Graphics 730\n"
)

ULTRA_CSV = (
    "Product,Status,Release Date,Code Name,Vertical Segment,Cores,Threads,"
    "Lithography(nm),Max. Turbo Freq.(GHz),Base Freq.(GHz),TDP(W),Cache(MB),"
    "Cache Info,Max Memory Size(GB),Memory Types,Max Memory Speed(MHz),"
    "Max Memory Channels,Integrated Graphics,Sockets Supported\n"
    "Core Ultra 5 322,Launched,Q1'26,Panther Lake,Mobile,6,6,2,4.40,2.50,55,12,"
    "Intel Smart Cache,128,Up to LPDDR5X 7467 MT/s,7467,2,Intel Graphics,FCBGA2540\n"
)

AMD_HTML = """
<html><body><table>
<dt>Name</dt><dd>AMD Ryzen 9 9950X3D</dd>
<dt>Family</dt><dd>Ryzen</dd>
<dt>Series</dt><dd>Ryzen 9000 Series</dd>
<dt>Former Codename</dt><dd>Granite Ridge AM5</dd>
<dt>Processor Architecture</dt><dd>Zen 5</dd>
<dt># of CPU Cores</dt><dd>16</dd>
<dt>Multithreading (SMT)</dt><dd>Yes</dd>
<dt># of Threads</dt><dd>32</dd>
<dt>Max. Boost Clock</dt><dd>Up to 5.7 GHz</dd>
<dt>Base Clock</dt><dd>4.3 GHz</dd>
<dt>L1 Cache</dt><dd>1280 KB</dd>
<dt>L2 Cache</dt><dd>16 MB</dd>
<dt>L3 Cache</dt><dd>128 MB</dd>
<dt>Default TDP</dt><dd>170W</dd>
<dt>CPU Socket</dt><dd>AM5</dd>
<dt>System Memory Type</dt><dd>DDR5</dd>
<dt>Max Memory Speed</dt><dd>2x1R DDR5-5600 2x2R DDR5-5600 4x1R DDR5-3600</dd>
<dt>Memory Channels</dt><dd>2</dd>
<dt>Graphics Model</dt><dd>AMD Radeon Graphics</dd>
<dt>Launch Date</dt><dd>03/12/2025</dd>
</table></body></html>
"""


def _insert_product(db, category, brand, model, vram_gb=None, cores=None):
    db.execute(
        "INSERT INTO products (category, brand, model, vram_gb, cores) VALUES (?, ?, ?, ?, ?)",
        (category, brand, model, vram_gb, cores),
    )
    return db.execute("SELECT id FROM products WHERE model = ?", (model,)).fetchone()[0]


# ── Parsers ───────────────────────────────────────────────────────────

class TestParseGpuRecords:
    def test_fields_mapped(self):
        recs = ss.parse_gpu_records(GPU_JSON)
        assert len(recs) == 2
        rec = next(r for r in recs if r["name"] == "GeForce RTX 4070 SUPER")
        assert rec["category"] == "gpu"
        assert rec["architecture"] == "Ada Lovelace"
        assert rec["generation"] == "GeForce 40"
        assert rec["launch_date"] == "2024-01-08"
        assert rec["vram_gb"] == 12.0
        assert rec["memory_bus_width_bit"] == 192
        assert rec["memory_type"] == "GDDR6X"
        assert rec["tdp_watts"] == 220
        assert rec["core_count"] == 7168
        assert rec["base_clock_mhz"] == 1980
        assert rec["boost_clock_mhz"] == 2475
        assert rec["cache_l3_mb"] is None  # l2Cache is not L3
        assert rec["gpu_die"] == "AD103"
        assert rec["bus_interface"] == "PCIe 4.0 x16"
        assert rec["memory_bandwidth_gbps"] == 504.2
        assert rec["memory_clock_mhz"] == 1313.0
        assert rec["process_nm"] == 5
        assert rec["foundry"] == "TSMC"
        assert rec["l2_cache_mb"] == 48.0
        assert rec["raw"]["name"] == "GeForce RTX 4070 SUPER"

    def test_missing_optional_fields_become_none(self):
        recs = ss.parse_gpu_records(json.dumps([{"name": "Mystery GPU"}]))
        assert recs[0]["vram_gb"] is None
        assert recs[0]["tdp_watts"] is None

    def test_malformed_json_raises(self):
        with pytest.raises(ss.SourceFetchError):
            ss.parse_gpu_records("{not json")

    def test_non_list_raises(self):
        with pytest.raises(ss.SourceFetchError):
            ss.parse_gpu_records(json.dumps({"name": "not a list"}))

    def test_records_without_name_skipped(self):
        recs = ss.parse_gpu_records(json.dumps([{"noName": True}, {"name": "GPU X"}]))
        assert len(recs) == 1
        assert recs[0]["name"] == "GPU X"


class TestParseIntelRecords:
    def test_fields_mapped(self):
        recs = ss.parse_intel_records([INTEL_CSV])
        assert len(recs) == 1
        rec = recs[0]
        assert rec["name"] == "Core i5-13400"
        assert rec["category"] == "cpu"
        assert rec["architecture"] == "Raptor Lake"
        assert rec["generation"] is None
        assert rec["launch_date"] == "Q1'23"  # stored verbatim
        assert rec["tdp_watts"] == 148
        assert rec["core_count"] == 10
        assert rec["thread_count"] == 16
        assert rec["base_clock_mhz"] == 2500
        assert rec["boost_clock_mhz"] == 4600
        assert rec["socket"] is None  # v1_8 has no socket column
        assert rec["cache_l3_mb"] == 20.0  # Intel 'Cache(MB)' = L3 for desktop
        assert rec["codename"] == "Raptor Lake"
        assert rec["process_nm"] == 7
        assert rec["memory_speed_mhz"] is None  # 'N/A' in the source
        assert rec["memory_types"] == "Up to DDR5 4800 MT/s"
        assert rec["integrated_graphics"] == "Intel UHD Graphics 730"

    def test_multiple_files_merged(self):
        recs = ss.parse_intel_records([INTEL_CSV, ULTRA_CSV])
        assert len(recs) == 2
        ultra = next(r for r in recs if r["name"] == "Core Ultra 5 322")
        assert ultra["socket"] == "FCBGA2540"
        assert ultra["architecture"] == "Panther Lake"
        assert ultra["cache_l3_mb"] == 12.0
        assert ultra["memory_speed_mhz"] == 7467
        assert ultra["memory_channels"] == 2

    def test_bom_stripped(self):
        recs = ss.parse_intel_records(["\ufeff" + INTEL_CSV])
        assert recs[0]["name"] == "Core i5-13400"

    def test_empty_text_raises(self):
        with pytest.raises(ss.SourceFetchError):
            ss.parse_intel_records(["   "])

    def test_header_only_raises(self):
        header = INTEL_CSV.split("\n")[0] + "\n"
        with pytest.raises(ss.SourceFetchError):
            ss.parse_intel_records([header])


class TestParseAmdRecord:
    def test_fields_mapped(self):
        rec = ss.parse_amd_record(AMD_HTML)
        assert rec is not None
        assert rec["name"] == "AMD Ryzen 9 9950X3D"
        assert rec["category"] == "cpu"
        assert rec["architecture"] == "Zen 5"
        assert rec["generation"] == "Ryzen 9000 Series"
        assert rec["launch_date"] == "2025-03-12"  # MM/DD/YYYY → ISO
        assert rec["tdp_watts"] == 170
        assert rec["core_count"] == 16
        assert rec["thread_count"] == 32
        assert rec["base_clock_mhz"] == 4300
        assert rec["boost_clock_mhz"] == 5700
        assert rec["socket"] == "AM5"
        assert rec["cache_l3_mb"] == 128.0
        assert rec["raw"]["CPU Socket"] == "AM5"
        assert rec["codename"] == "Granite Ridge"
        assert rec["l1_cache_kb"] == 1280.0
        assert rec["l2_cache_mb"] == 16.0
        assert rec["memory_speed_mhz"] == 5600
        assert rec["memory_channels"] == 2
        assert rec["memory_types"] == "DDR5"
        assert rec["integrated_graphics"] == "AMD Radeon Graphics"

    def test_no_spec_table_returns_none(self):
        assert ss.parse_amd_record("<html><body><p>no table</p></body></html>") is None

    def test_name_sanitized_of_control_chars(self):
        html = "<dt>Name</dt><dd>AMD Ryzen\x84 9 9950X3D</dd>"
        rec = ss.parse_amd_record(html)
        assert rec is not None
        assert rec["name"] == "AMD Ryzen 9 9950X3D"


class TestValueHelpers:
    @pytest.mark.parametrize("value,expected", [
        ("4.60", 4600),
        ("4.3 GHz", 4300),
        ("Up to 5.7 GHz", 5700),
        ("", None),
        (None, None),
        ("N/A", None),
    ])
    def test_ghz_to_mhz(self, value, expected):
        assert ss._ghz_to_mhz(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("170W", "170"),
        ("128 MB", "128"),
        ("4.3 GHz", "4.3"),
        ("plain", "plain"),
        (None, None),
    ])
    def test_strip_unit(self, value, expected):
        unit = {"170W": "W", "128 MB": "MB", "4.3 GHz": "GHz", "plain": ""}[value] if value else ""
        assert ss._strip_unit(value, unit) == expected

    @pytest.mark.parametrize("value,expected", [
        ("03/12/2025", "2025-03-12"),
        ("1/5/2024", "2024-01-05"),
        ("13/40/2025", None),
        ("Q1'23", None),
        (None, None),
    ])
    def test_amd_launch_date_to_iso(self, value, expected):
        assert ss._amd_launch_date_to_iso(value) == expected

    def test_sanitize_name(self):
        assert ss._sanitize_name("AMD Ryzen\x84 9 9950X3D") == "AMD Ryzen 9 9950X3D"
        assert ss._sanitize_name("AMD Ryzen™ 9 9950X3D") == "AMD Ryzen™ 9 9950X3D"


class TestAmdUrl:
    def test_9000_series(self):
        assert ss.amd_url_for("Ryzen 9 9950X3D") == (
            "https://www.amd.com/en/products/processors/desktops/ryzen/"
            "9000-series/amd-ryzen-9-9950x3d.html"
        )

    def test_5000_series(self):
        assert ss.amd_url_for("Ryzen 5 5500") == (
            "https://www.amd.com/en/products/processors/desktops/ryzen/"
            "5000-series/amd-ryzen-5-5500.html"
        )

    def test_8000_series_apu(self):
        assert ss.amd_url_for("Ryzen 5 8600G") == (
            "https://www.amd.com/en/products/processors/desktops/ryzen/"
            "8000-series/amd-ryzen-5-8600g.html"
        )

    def test_unrecognised_series_returns_none(self):
        assert ss.amd_url_for("Ryzen 3 3200G") is None


# ── fetch_url ─────────────────────────────────────────────────────────

class TestFetchUrl:
    def test_200_returns_body(self, monkeypatch):
        r = mock.Mock(status_code=200, content="hello".encode())
        monkeypatch.setattr(ss.requests, "get", lambda *a, **k: r)
        assert ss.fetch_url("http://x") == "hello"

    def test_404_is_definitive_no_retry(self, monkeypatch):
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append(url)
            return mock.Mock(status_code=404, content=b"")

        monkeypatch.setattr(ss.requests, "get", fake_get)
        assert ss.fetch_url("http://x", retries=2) is None
        assert len(calls) == 1  # no retries on 4xx

    def test_503_retried_then_success(self, monkeypatch):
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append(1)
            if len(calls) < 3:
                return mock.Mock(status_code=503, content=b"")
            return mock.Mock(status_code=200, content="ok".encode())

        monkeypatch.setattr(ss.requests, "get", fake_get)
        monkeypatch.setattr(ss.time, "sleep", lambda s: None)
        assert ss.fetch_url("http://x") == "ok"
        assert len(calls) == 3

    def test_network_error_retried_then_gives_up(self, monkeypatch):
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append(1)
            raise ss.requests.RequestException("boom")

        monkeypatch.setattr(ss.requests, "get", fake_get)
        monkeypatch.setattr(ss.time, "sleep", lambda s: None)
        assert ss.fetch_url("http://x", retries=1) is None
        assert len(calls) == 2


# ── fetch_amd_records ─────────────────────────────────────────────────

class TestFetchAmdRecords:
    def test_partial_404_tolerated(self, monkeypatch):
        def fake_fetch(url, headers=None, retries=2, timeout=20):
            if "5500" in url:
                return None  # OEM-only part, no amd.com page
            return AMD_HTML

        monkeypatch.setattr(ss, "fetch_url", fake_fetch)
        monkeypatch.setattr(ss.time, "sleep", lambda s: None)
        records, failed = ss.fetch_amd_records(["Ryzen 9 9950X3D", "Ryzen 5 5500"])
        assert len(records) == 1
        assert records[0]["name"] == "AMD Ryzen 9 9950X3D"
        assert len(failed) == 1
        assert failed[0]["model"] == "Ryzen 5 5500"

    def test_unrecognised_series_reported(self, monkeypatch):
        monkeypatch.setattr(ss, "fetch_url", lambda *a, **k: AMD_HTML)
        monkeypatch.setattr(ss.time, "sleep", lambda s: None)
        records, failed = ss.fetch_amd_records(["Ryzen 3 3200G"])
        assert records == []
        assert failed[0]["model"] == "Ryzen 3 3200G"


# ── sync_source ───────────────────────────────────────────────────────

class TestSyncSource:
    def test_fresh_sync_inserts(self, db):
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        stats = ss.sync_source("gpu", ss.SOURCE_GPU, ss.parse_gpu_records(GPU_JSON),
                               db, ss.load_products(db, "gpu"))
        assert stats["matched_new"] == 1
        row = db.execute("SELECT * FROM specs").fetchone()
        assert row["source"] == ss.SOURCE_GPU
        assert row["source_record_key"] == "GeForce RTX 4070 SUPER"
        assert row["vram_gb"] == 12.0
        assert row["tdp_watts"] == 220
        assert row["core_count"] == 7168
        assert row["gpu_die"] == "AD103"
        assert row["bus_interface"] == "PCIe 4.0 x16"
        assert row["memory_bandwidth_gbps"] == 504.2
        assert row["process_nm"] == 5
        assert row["foundry"] == "TSMC"
        assert row["l2_cache_mb"] == 48.0
        assert row["last_synced_at"].endswith("Z")
        assert json.loads(row["raw_json"])["name"] == "GeForce RTX 4070 SUPER"

    def test_resync_unchanged_refreshes_timestamp(self, db):
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        recs = ss.parse_gpu_records(GPU_JSON)
        ss.sync_source("gpu", ss.SOURCE_GPU, recs, db, ss.load_products(db, "gpu"))
        db.execute("UPDATE specs SET last_synced_at = '2000-01-01T00:00:00Z'")
        db.commit()

        stats = ss.sync_source("gpu", ss.SOURCE_GPU, recs, db, ss.load_products(db, "gpu"))
        assert stats["matched_new"] == 0
        assert stats["matched_unchanged"] == 1
        row = db.execute("SELECT last_synced_at FROM specs").fetchone()
        assert row[0] != "2000-01-01T00:00:00Z"

    def test_conflict_not_overwritten(self, db):
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        recs = ss.parse_gpu_records(GPU_JSON)
        ss.sync_source("gpu", ss.SOURCE_GPU, recs, db, ss.load_products(db, "gpu"))
        db.execute("UPDATE specs SET raw_json = raw_json || ' '")  # simulate upstream change
        db.commit()

        stats = ss.sync_source("gpu", ss.SOURCE_GPU, recs, db, ss.load_products(db, "gpu"))
        assert stats["matched_new"] == 0
        assert stats["matched_unchanged"] == 0
        assert len(stats["conflicts"]) == 1
        assert stats["conflicts"][0]["model"] == "GeForce RTX 4070 Super"
        # row untouched
        row = db.execute("SELECT raw_json FROM specs").fetchone()
        assert row[0].endswith(" ")

    def test_unmatched_reported_no_row(self, db):
        _insert_product(db, "gpu", "AMD", "Radeon RX 9070 XTX", vram_gb=32)
        stats = ss.sync_source("gpu", ss.SOURCE_GPU, ss.parse_gpu_records(GPU_JSON),
                               db, ss.load_products(db, "gpu"))
        assert stats["matched_new"] == 0
        assert len(stats["unmatched_products"]) == 1
        assert stats["unmatched_products"][0]["model"] == "Radeon RX 9070 XTX"
        assert db.execute("SELECT COUNT(*) FROM specs").fetchone()[0] == 0

    def test_dry_run_no_writes(self, db):
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        stats = ss.sync_source("gpu", ss.SOURCE_GPU, ss.parse_gpu_records(GPU_JSON),
                               db, ss.load_products(db, "gpu"), dry_run=True)
        assert stats["matched_new"] == 1  # counted, but...
        assert db.execute("SELECT COUNT(*) FROM specs").fetchone()[0] == 0  # ...not written

    def test_existing_row_kept_when_record_disappears(self, db):
        """Never-delete: a product whose upstream record vanishes keeps its row."""
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        recs = ss.parse_gpu_records(GPU_JSON)
        ss.sync_source("gpu", ss.SOURCE_GPU, recs, db, ss.load_products(db, "gpu"))
        db.execute("UPDATE specs SET last_synced_at = '2000-01-01T00:00:00Z'")
        db.commit()

        # Second sync where the record is gone upstream
        stats = ss.sync_source("gpu", ss.SOURCE_GPU, [], db, ss.load_products(db, "gpu"))
        assert len(stats["unmatched_products"]) == 1
        row = db.execute("SELECT last_synced_at FROM specs").fetchone()
        assert row[0] == "2000-01-01T00:00:00Z"  # row kept, timestamp untouched

    def test_amd_records_match_cpu_products(self, db):
        _insert_product(db, "cpu", "AMD", "Ryzen 9 9950X3D", cores=16)
        amd_rec = ss.parse_amd_record(AMD_HTML)
        assert amd_rec is not None
        stats = ss.sync_source("cpu", ss.SOURCE_AMD, [amd_rec],
                               db, ss.load_products(db, "cpu"))
        assert stats["matched_new"] == 1
        row = db.execute("SELECT * FROM specs").fetchone()
        assert row["socket"] == "AM5"
        assert row["cache_l3_mb"] == 128.0
        assert row["thread_count"] == 32


# ── backfill_specs_extra ─────────────────────────────────────────────

class TestBackfillSpecsExtra:
    def test_backfills_gpu_from_raw_json(self, db):
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        recs = ss.parse_gpu_records(GPU_JSON)
        ss.sync_source("gpu", ss.SOURCE_GPU, recs, db, ss.load_products(db, "gpu"))
        db.execute(
            "UPDATE specs SET gpu_die = NULL, bus_interface = NULL, process_nm = NULL"
        )
        db.commit()

        updated = ss.backfill_specs_extra(db)
        assert updated == 1
        row = db.execute("SELECT gpu_die, bus_interface, process_nm FROM specs").fetchone()
        assert row["gpu_die"] == "AD103"
        assert row["bus_interface"] == "PCIe 4.0 x16"
        assert row["process_nm"] == 5

    def test_backfills_intel_cache_l3(self, db):
        _insert_product(db, "cpu", "Intel", "Core i5-13400", cores=10)
        recs = ss.parse_intel_records([INTEL_CSV])
        ss.sync_source("cpu", ss.SOURCE_INTEL, recs, db, ss.load_products(db, "cpu"))
        db.execute("UPDATE specs SET cache_l3_mb = NULL")
        db.commit()

        updated = ss.backfill_specs_extra(db)
        assert updated == 1
        row = db.execute(
            "SELECT cache_l3_mb, codename, memory_types FROM specs"
        ).fetchone()
        assert row["cache_l3_mb"] == 20.0
        assert row["codename"] == "Raptor Lake"
        assert row["memory_types"] == "Up to DDR5 4800 MT/s"

    def test_backfills_amd_from_raw_json(self, db):
        _insert_product(db, "cpu", "AMD", "Ryzen 9 9950X3D", cores=16)
        rec = ss.parse_amd_record(AMD_HTML)
        assert rec is not None
        ss.sync_source("cpu", ss.SOURCE_AMD, [rec], db, ss.load_products(db, "cpu"))
        db.execute(
            "UPDATE specs SET codename = NULL, l1_cache_kb = NULL, "
            "memory_speed_mhz = NULL, memory_channels = NULL"
        )
        db.commit()

        updated = ss.backfill_specs_extra(db)
        assert updated == 1
        row = db.execute(
            "SELECT codename, l1_cache_kb, memory_speed_mhz, memory_channels FROM specs"
        ).fetchone()
        assert row["codename"] == "Granite Ridge"
        assert row["l1_cache_kb"] == 1280.0
        assert row["memory_speed_mhz"] == 5600
        assert row["memory_channels"] == 2

    def test_idempotent(self, db):
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        recs = ss.parse_gpu_records(GPU_JSON)
        ss.sync_source("gpu", ss.SOURCE_GPU, recs, db, ss.load_products(db, "gpu"))
        db.execute("UPDATE specs SET gpu_die = NULL")
        db.commit()

        assert ss.backfill_specs_extra(db) == 1
        assert ss.backfill_specs_extra(db) == 0  # nothing left to fill

    def test_dry_run_does_not_write(self, db):
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        recs = ss.parse_gpu_records(GPU_JSON)
        ss.sync_source("gpu", ss.SOURCE_GPU, recs, db, ss.load_products(db, "gpu"))
        db.execute("UPDATE specs SET gpu_die = NULL")
        db.commit()

        updated = ss.backfill_specs_extra(db, dry_run=True)
        assert updated == 1
        row = db.execute("SELECT gpu_die FROM specs").fetchone()
        assert row["gpu_die"] is None

    def test_skips_when_extra_columns_missing(self, db):
        """An un-migrated DB (no extra columns) is left untouched."""
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        # Fake a pre-migration schema: rebuild specs without the new columns.
        db.execute("DROP TABLE specs")
        db.execute(
            """CREATE TABLE specs (
                spec_id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_record_key TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('gpu','cpu','ram','storage','motherboard','psu','case','cooling')),
                architecture TEXT,
                generation TEXT,
                launch_date TEXT,
                launch_msrp_usd REAL,
                vram_gb REAL,
                memory_bus_width_bit INTEGER,
                memory_type TEXT,
                tdp_watts INTEGER,
                core_count INTEGER,
                thread_count INTEGER,
                base_clock_mhz INTEGER,
                boost_clock_mhz INTEGER,
                socket TEXT,
                cache_l3_mb REAL,
                raw_json TEXT NOT NULL,
                last_synced_at TEXT NOT NULL
            )"""
        )
        pid = db.execute("SELECT id FROM products WHERE model = 'GeForce RTX 4070 Super'").fetchone()[0]
        db.execute(
            "INSERT INTO specs (product_id, source, source_record_key, category, "
            "architecture, vram_gb, tdp_watts, cache_l3_mb, raw_json, last_synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, ss.SOURCE_GPU, "GeForce RTX 4070 SUPER", "gpu", "Ada Lovelace",
             12.0, 220, None, json.dumps(json.loads(GPU_JSON)[0]), "2026-08-16T00:00:00Z"),
        )
        db.commit()

        assert ss.backfill_specs_extra(db) == 0  # gracefully skipped
        row = db.execute("SELECT cache_l3_mb FROM specs").fetchone()
        assert row[0] is None


# ── main entry point ──────────────────────────────────────────────────

def _make_db_file(path, products):
    """Create a file DB with schema + products."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    for category, brand, model, vram_gb, cores in products:
        conn.execute(
            "INSERT INTO products (category, brand, model, vram_gb, cores) VALUES (?, ?, ?, ?, ?)",
            (category, brand, model, vram_gb, cores),
        )
    conn.commit()
    conn.close()


def _count_specs(path):
    conn = sqlite3.connect(str(path))
    n = conn.execute("SELECT COUNT(*) FROM specs").fetchone()[0]
    conn.close()
    return n


class TestMain:
    def _setup(self, tmp_path, monkeypatch, gpu_records=None, intel_records=None,
               amd_records=None, amd_failed=None):
        db_file = tmp_path / "t.db"
        _make_db_file(db_file, [
            ("gpu", "NVIDIA", "GeForce RTX 4070 Super", 12, None),
            ("cpu", "Intel", "Core i5-13400", None, 10),
            ("cpu", "AMD", "Ryzen 9 9950X3D", None, 16),
        ])
        monkeypatch.setattr(ss, "DB_PATH", db_file)
        monkeypatch.setattr(ss, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(ss, "fetch_gpu_records",
                            lambda: gpu_records if gpu_records is not None else ss.parse_gpu_records(GPU_JSON))
        monkeypatch.setattr(ss, "fetch_intel_records",
                            lambda: intel_records if intel_records is not None else ss.parse_intel_records([INTEL_CSV, ULTRA_CSV]))
        monkeypatch.setattr(ss, "fetch_amd_records",
                            lambda models: (amd_records if amd_records is not None else [ss.parse_amd_record(AMD_HTML)],
                                            amd_failed or []))
        return db_file

    def test_fresh_sync_writes_rows_and_report(self, tmp_path, monkeypatch):
        db_file = self._setup(tmp_path, monkeypatch)
        ss.main([])
        assert _count_specs(db_file) == 3
        report_file = tmp_path / "data" / ss.REPORT_FILENAME
        assert report_file.exists()
        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert report["summary"]["matched_new"] == 3
        assert report["failed_sources"] == []
        assert set(report["sources"]) == {ss.SOURCE_GPU, ss.SOURCE_INTEL, ss.SOURCE_AMD}

    def test_dry_run_no_writes_no_report(self, tmp_path, monkeypatch):
        db_file = self._setup(tmp_path, monkeypatch)
        ss.main(["--dry-run"])
        assert _count_specs(db_file) == 0
        assert not (tmp_path / "data" / ss.REPORT_FILENAME).exists()

    def test_category_filter(self, tmp_path, monkeypatch):
        db_file = self._setup(tmp_path, monkeypatch)
        ss.main(["--category", "gpu"])
        rows = sqlite3.connect(str(db_file)).execute(
            "SELECT source FROM specs"
        ).fetchall()
        assert [r[0] for r in rows] == [ss.SOURCE_GPU]

    def test_partial_failure_isolation(self, tmp_path, monkeypatch):
        """GPU source failure must not prevent the CPU sources from syncing."""
        db_file = self._setup(tmp_path, monkeypatch)

        def gpu_boom():
            raise ss.SourceFetchError("GPU source unreachable")

        monkeypatch.setattr(ss, "fetch_gpu_records", gpu_boom)
        with pytest.raises(SystemExit) as exc:
            ss.main([])
        assert exc.value.code == 1
        # CPU sources still synced
        assert _count_specs(db_file) == 2
        report = json.loads((tmp_path / "data" / ss.REPORT_FILENAME).read_text(encoding="utf-8"))
        assert report["failed_sources"][0]["source"] == ss.SOURCE_GPU
        assert ss.SOURCE_INTEL in report["sources"]
        assert ss.SOURCE_AMD in report["sources"]

    def test_report_only_prints_and_does_not_fetch(self, tmp_path, monkeypatch, capsys):
        db_file = self._setup(tmp_path, monkeypatch)
        ss.main([])  # produce a report

        def boom():
            raise AssertionError("fetchers must not be called in report-only mode")

        monkeypatch.setattr(ss, "fetch_gpu_records", boom)
        monkeypatch.setattr(ss, "fetch_intel_records", boom)
        monkeypatch.setattr(ss, "fetch_amd_records", boom)
        ss.main(["--report-only"])
        out = capsys.readouterr().out
        assert '"matched_new": 3' in out

    def test_report_only_without_report_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        db_file = tmp_path / "t.db"
        _make_db_file(db_file, [])
        monkeypatch.setattr(ss, "DB_PATH", db_file)
        monkeypatch.setattr(ss, "DATA_DIR", tmp_path / "data")
        with pytest.raises(SystemExit) as exc:
            ss.main(["--report-only"])
        assert exc.value.code == 1

    def test_missing_db_exits_nonzero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "DB_PATH", tmp_path / "nope.db")
        with pytest.raises(SystemExit) as exc:
            ss.main([])
        assert exc.value.code == 1


# ── seed export / import (--export / --import) ───────────────────────

class TestSeedExportImport:
    def _seed_row(self, db, path):
        """Insert a product + gpu spec row, then export it to path."""
        _insert_product(db, "gpu", "NVIDIA", "GeForce RTX 4070 Super", vram_gb=12)
        ss.sync_source("gpu", ss.SOURCE_GPU, ss.parse_gpu_records(GPU_JSON),
                       db, ss.load_products(db, "gpu"))
        n = ss.export_specs(db, path)
        assert n == 1
        return path

    def test_export_json_shape(self, db, tmp_path):
        out = tmp_path / "specs_seed.json"
        self._seed_row(db, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data) == 1
        row = data[0]
        assert set(row.keys()) == set(ss._SEED_COLUMNS)
        assert "spec_id" not in row
        assert row["product_id"] == 1
        assert row["vram_gb"] == 12.0
        assert row["tdp_watts"] == 220
        assert row["gpu_die"] == "AD103"
        assert isinstance(row["raw_json"], str)  # raw stays a JSON string

    def test_import_restores_rows(self, db, tmp_path):
        out = tmp_path / "specs_seed.json"
        self._seed_row(db, out)
        db.execute("DELETE FROM specs")
        db.commit()
        n = ss.import_specs(db, out)
        assert n == 1
        row = db.execute("SELECT * FROM specs").fetchone()
        assert row["product_id"] == 1
        assert row["gpu_die"] == "AD103"
        assert row["memory_bandwidth_gbps"] == 504.2

    def test_import_idempotent(self, db, tmp_path):
        out = tmp_path / "specs_seed.json"
        self._seed_row(db, out)
        db.execute("DELETE FROM specs")
        db.commit()
        ss.import_specs(db, out)
        ss.import_specs(db, out)  # re-import must not duplicate
        assert db.execute("SELECT COUNT(*) FROM specs").fetchone()[0] == 1

    def test_import_replaces_existing(self, db, tmp_path):
        """INSERT OR REPLACE keys on (product_id, source), so a diverged row
        is overwritten with the seed value (bootstrap is authoritative)."""
        out = tmp_path / "specs_seed.json"
        self._seed_row(db, out)
        db.execute("UPDATE specs SET raw_json = raw_json || ' '")
        db.commit()
        n = ss.import_specs(db, out)
        assert n == 1
        row = db.execute("SELECT raw_json FROM specs").fetchone()
        assert not row[0].endswith(" ")

    def test_import_dry_run_no_writes(self, db, tmp_path):
        out = tmp_path / "specs_seed.json"
        self._seed_row(db, out)
        db.execute("DELETE FROM specs")
        db.commit()
        n = ss.import_specs(db, out, dry_run=True)
        assert n == 1
        assert db.execute("SELECT COUNT(*) FROM specs").fetchone()[0] == 0

    def test_import_rejects_non_list(self, db, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with pytest.raises(ValueError):
            ss.import_specs(db, bad)

    def test_main_export_flag(self, tmp_path, monkeypatch):
        db_file = tmp_path / "t.db"
        _make_db_file(db_file, [("gpu", "NVIDIA", "GeForce RTX 4070 Super", 12, None)])
        conn = sqlite3.connect(str(db_file))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        ss.sync_source("gpu", ss.SOURCE_GPU, ss.parse_gpu_records(GPU_JSON),
                       conn, ss.load_products(conn, "gpu"))
        conn.close()
        monkeypatch.setattr(ss, "DB_PATH", db_file)
        out = tmp_path / "specs_seed.json"
        ss.main(["--export", str(out)])
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data[0]["source"] == ss.SOURCE_GPU

    def test_main_import_flag(self, tmp_path, monkeypatch):
        db_file = tmp_path / "t.db"
        _make_db_file(db_file, [("gpu", "NVIDIA", "GeForce RTX 4070 Super", 12, None)])
        conn = sqlite3.connect(str(db_file))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        ss.sync_source("gpu", ss.SOURCE_GPU, ss.parse_gpu_records(GPU_JSON),
                       conn, ss.load_products(conn, "gpu"))
        out = tmp_path / "specs_seed.json"
        ss.export_specs(conn, out)
        conn.execute("DELETE FROM specs")
        conn.commit()
        conn.close()
        monkeypatch.setattr(ss, "DB_PATH", db_file)
        ss.main(["--import", str(out)])
        assert _count_specs(db_file) == 1

    def test_main_export_missing_db_exits_nonzero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "DB_PATH", tmp_path / "nope.db")
        with pytest.raises(SystemExit) as exc:
            ss.main(["--export", str(tmp_path / "s.json")])
        assert exc.value.code == 1

    def test_main_import_missing_file_exits_nonzero(self, tmp_path, monkeypatch):
        db_file = tmp_path / "t.db"
        _make_db_file(db_file, [])
        monkeypatch.setattr(ss, "DB_PATH", db_file)
        with pytest.raises(SystemExit) as exc:
            ss.main(["--import", str(tmp_path / "nope.json")])
        assert exc.value.code == 1

    def test_main_export_import_mutually_exclusive(self, tmp_path, monkeypatch):
        db_file = tmp_path / "t.db"
        _make_db_file(db_file, [])
        monkeypatch.setattr(ss, "DB_PATH", db_file)
        with pytest.raises(SystemExit) as exc:
            ss.main(["--export", "a", "--import", "b"])
        assert exc.value.code == 2
