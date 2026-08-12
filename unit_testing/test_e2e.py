"""
End-to-end pipeline tests: scrape-shaped JSON -> ingest -> query -> health checks.

The scrapers, ingestion, query tool, and health checks are each unit-tested in
isolation, but nothing chains them together. These tests run real stages in
sequence against a file-backed temp DB to catch contract drift between modules
(e.g. a scraper renaming a key that ingest.py reads, or a query assuming a
field the health checks never populate).

The scrape-shaped JSON in the synthetic test uses the exact key set the real
scrapers emit (see scraper/pccg.py match dicts), so a contract change on either
side of the pipeline is caught here.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys_path = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, sys_path)

from ingest import ingest_file
from health_checks import CheckResult, check_db_freshness, check_match_count_anomalies, check_price_anomalies
from query import show_biggest_movers, show_latest_prices, show_trends

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _scrape_record(model, category, brand, gen_tier, retailer, scraped_name, price, url):
    """A matched product exactly as a scraper emits it."""
    return {
        "watchlist_model": model,
        "watchlist_category": category,
        "watchlist_brand": brand,
        "watchlist_gen_tier": gen_tier,
        "retailer": retailer,
        "scraped_name": scraped_name,
        "price_aud": price,
        "stock_status": "in_stock",
        "url": url,
    }


def _write_scrape_json(tmp_path, category, retailer, date_str, records):
    """Write a single scrape output file with the real key set."""
    data = {
        "retailer": retailer,
        "scrape_date": date_str,
        "category": category,
        "total_watchlist": len(records),
        "matched": len(records),
        "unmatched_count": 0,
        "unmatched_models": [],
        "products": records,
    }
    file_path = tmp_path / f"{category}_{retailer}_{date_str}.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    return file_path


class TestEndToEndSynthetic:
    """Scrape-shaped JSON -> ingest -> query -> health checks, always runs."""

    def _build_scenes(self, tmp_path):
        """Two days of scrape output: day 1 stable, day 2 with one price jump."""
        day1 = [
            _scrape_record("GeForce RTX 5070 Ti", "gpu", "NVIDIA", "current",
                           "scorptec", "GIGABYTE RTX 5070 Ti OC 16GB", 999.0,
                           "https://scorptec.com.au/products/5070ti"),
            _scrape_record("Ryzen 7 9800X3D", "cpu", "AMD", "current",
                           "scorptec", "AMD Ryzen 7 9800X3D 8 Core", 599.0,
                           "https://scorptec.com.au/products/9800x3d"),
            _scrape_record("GeForce RTX 5070 Ti", "gpu", "NVIDIA", "current",
                           "pccg", "ASUS RTX 5070 Ti TUF Gaming", 1029.0,
                           "https://pccg.com/products/5070ti-asus"),
        ]
        file1 = _write_scrape_json(tmp_path, "cpu", "scorptec", "10_August_2026",
                                   [r for r in day1 if r["watchlist_category"] == "cpu"])
        file1b = _write_scrape_json(tmp_path, "gpu", "scorptec", "10_August_2026",
                                    [r for r in day1 if r["watchlist_category"] == "gpu"])
        file1c = _write_scrape_json(tmp_path, "gpu", "pccg", "10_August_2026",
                                    [r for r in day1 if r["retailer"] == "pccg"])

        # Day 2: RTX 5070 Ti @ Scorptec jumps from 999 -> 1299
        jumped = _scrape_record("GeForce RTX 5070 Ti", "gpu", "NVIDIA", "current",
                                "scorptec", "GIGABYTE RTX 5070 Ti OC 16GB", 1299.0,
                                "https://scorptec.com.au/products/5070ti")
        day2 = [
            jumped,
            _scrape_record("Ryzen 7 9800X3D", "cpu", "AMD", "current",
                           "scorptec", "AMD Ryzen 7 9800X3D 8 Core", 599.0,
                           "https://scorptec.com.au/products/9800x3d"),
            _scrape_record("GeForce RTX 5070 Ti", "gpu", "NVIDIA", "current",
                           "pccg", "ASUS RTX 5070 Ti TUF Gaming", 1029.0,
                           "https://pccg.com/products/5070ti-asus"),
        ]
        file2 = _write_scrape_json(tmp_path, "gpu", "scorptec", "11_August_2026",
                                   [r for r in day2 if r["retailer"] == "scorptec"])

        return [file1, file1b, file1c, file2]

    def test_scrape_to_query_to_health(self, tmp_path, db_path):
        """Each pipeline stage consumes the previous stage's output cleanly."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row

        # ── Stage 1: ingest (no scrape networking — synthetic scrape output)
        total_inserted = 0
        for f in self._build_scenes(tmp_path):
            stats = ingest_file(conn, f)
            assert stats["errors"] == 0
            total_inserted += stats["inserted"]
        assert total_inserted > 0
        conn.commit()

        # ── Stage 2: query tools read what ingest wrote
        import contextlib
        from io import StringIO

        out = StringIO()
        with contextlib.redirect_stdout(out):
            show_latest_prices(conn)
            movers_out = StringIO()
            with contextlib.redirect_stdout(movers_out):
                show_biggest_movers(conn)
        assert "1299.00" in movers_out.getvalue() or "+300.00" in movers_out.getvalue()

        # ── Stage 3: health checks validate DB state without errors
        results = (
            check_db_freshness(db_path)
            + check_match_count_anomalies(db_path)
            + check_price_anomalies(db_path)
        )
        assert not [r for r in results if r.status == CheckResult.ERROR], results
        conn.close()

    def test_variant_name_survives_pipeline(self, tmp_path, db_path):
        """scraped_name flows through to retailer_listings.variant_name."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row

        f = _write_scrape_json(tmp_path, "gpu", "scorptec", "12_August_2026", [
            _scrape_record("GeForce RTX 5090", "gpu", "NVIDIA", "current",
                           "scorptec", "GIGABYTE AORUS RTX 5090 AI Box, 32GB", 6599.0,
                           "https://scorptec.com.au/products/5090-giga"),
        ])
        stats = ingest_file(conn, f)
        assert stats["inserted"] == 1

        variant = conn.execute(
            "SELECT variant_name FROM retailer_listings WHERE listing_url = ?",
            ("https://scorptec.com.au/products/5090-giga",),
        ).fetchone()[0]
        assert variant == "GIGABYTE AORUS RTX 5090 AI Box, 32GB"
        conn.close()


class TestEndToEndRealData:
    """True scraper output -> ingest -> query, using the live data/ files."""

    def test_all_real_snapshots_ingest_error_free(self, tmp_path, db_path):
        files = sorted(
            f for f in DATA_DIR.glob("*.json")
            if ".backup" not in f.name  # Skip backup/archive files
        )
        if not files:
            pytest.skip("No real scraped JSON files available in data/")

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row

        total_inserted = 0
        for f in files:
            stats = ingest_file(conn, f)
            assert stats["errors"] == 0, f"Ingest contract broken for {f.name}: {stats}"
            total_inserted += stats["inserted"]
        assert total_inserted > 0
        conn.commit()

        # Query tools run over the full real dataset without raising.
        import contextlib
        from io import StringIO

        out = StringIO()
        with contextlib.redirect_stdout(out):
            show_latest_prices(conn)
            show_trends(conn)
            show_biggest_movers(conn)
        assert "No data found." not in out.getvalue()

        # Health checks agree the DB is coherent.
        results = (
            check_db_freshness(db_path)
            + check_match_count_anomalies(db_path)
        )
        assert not [r for r in results if r.status == CheckResult.ERROR], results
        conn.close()