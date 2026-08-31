"""
Tests that `umart` is threaded through every place a retailer name is expected.

THIRD_RETAILER.md's central point was that the scraper is the *small* half: the
retailer name was hardcoded in at least nine places, and missing one means the
new data is silently dropped or rejected rather than failing loudly.

These tests pin the wiring. Most of them assert against
``config.ACTIVE_RETAILERS`` -- the single list those nine sites now read from,
so that retailer four is a one-line change instead of a nine-file hunt.

``ACTIVE_RETAILERS`` (what we scrape today) is deliberately *not*
``migrate.PERMITTED_RETAILERS`` (what the database will accept). The schema
tolerates six so the CHECK never needs another table rebuild; only three are
scraped, and a health check that expected all six would alarm every morning
about retailers that have no scraper.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import check_staleness  # noqa: E402
import health_checks  # noqa: E402
from ingest import extract_listing_key, is_snapshot_file  # noqa: E402
from migrate import PERMITTED_RETAILERS  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class TestActiveRetailers:
    def test_lists_the_three_retailers_with_scrapers(self):
        assert set(config.ACTIVE_RETAILERS) == {"scorptec", "pccg", "umart"}

    def test_is_a_subset_of_what_the_database_permits(self):
        """Scraping a retailer the schema rejects would fail at INSERT."""
        assert set(config.ACTIVE_RETAILERS) <= set(PERMITTED_RETAILERS)

    def test_is_narrower_than_what_the_database_permits(self):
        """The schema tolerates retailers we do not scrape; health checks must
        not expect data from them."""
        assert set(config.ACTIVE_RETAILERS) < set(PERMITTED_RETAILERS)


class TestIngestAcceptsUmart:
    def test_recognises_a_umart_snapshot_filename(self):
        assert is_snapshot_file("gpu_umart_31_August_2026.json")
        assert is_snapshot_file("cpu_umart_31_August_2026.json")

    def test_still_rejects_a_retailer_with_no_scraper(self):
        """mwave is permitted by the schema but has no scraper; a file claiming
        to be one is malformed, not something to ingest."""
        assert not is_snapshot_file("cpu_mwave_10_August_2026.json")

    def test_extracts_the_listing_key_from_a_umart_url(self):
        """Umart product URLs end in the numeric id that is also `data-id`."""
        url = (
            "https://www.umart.com.au/product/"
            "asus-dual-geforce-rtx-5060-8g-oc-advanced-graphics-card-dual-rtx5060-o8g-a-95655"
        )
        assert extract_listing_key("umart", url) == "95655"

    def test_a_umart_url_without_a_trailing_id_has_no_key(self):
        assert extract_listing_key("umart", "https://www.umart.com.au/product/mystery") is None


class TestStalenessMonitorWatchesUmart:
    def test_expects_umart(self):
        """The monitor exists to notice a scraper that stopped running. One it
        does not know about is one it cannot miss."""
        assert "umart" in check_staleness.EXPECTED_RETAILERS

    def test_matches_the_shared_list(self):
        assert set(check_staleness.EXPECTED_RETAILERS) == set(config.ACTIVE_RETAILERS)


class TestHealthChecksWatchUmart:
    def _db(self, tmp_path):
        db = tmp_path / "h.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO products (category, brand, model, tracked) "
            "VALUES ('gpu', 'NVIDIA', 'RTX 5060', 1)"
        )
        # scorptec and pccg have a listing today; umart has none.
        for i, retailer in enumerate(("scorptec", "pccg"), start=1):
            conn.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                "VALUES (1, ?, ?, 'active')",
                (retailer, f"https://{retailer}/{i}"),
            )
            conn.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                "VALUES (?, date('now'), 599.0, 'in_stock')",
                (i,),
            )
        conn.commit()
        conn.close()
        return db

    def test_reports_a_umart_with_no_data_today(self, tmp_path):
        """Silence from a retailer we scrape has to be visible, not absent."""
        results = health_checks.check_today_coverage(self._db(tmp_path))
        assert any("umart" in r.message.lower() for r in results), results


class TestDailyRunnerRunsUmart:
    """The scraper exists, but nothing collects from it until run_daily does."""

    def _parse(self, argv):
        import run_daily

        parser = run_daily.build_parser()
        return parser.parse_args(argv)

    def test_offers_a_flag_per_active_retailer(self):
        args = self._parse(["--umart"])
        assert args.umart is True
        assert args.scorptec is False

    def test_no_retailer_flag_means_every_retailer(self):
        import run_daily

        assert run_daily.selected_retailers(self._parse([])) == list(config.ACTIVE_RETAILERS)

    def test_a_single_flag_narrows_to_that_retailer(self):
        import run_daily

        assert run_daily.selected_retailers(self._parse(["--umart"])) == ["umart"]

    def test_flags_combine(self):
        import run_daily

        assert run_daily.selected_retailers(self._parse(["--umart", "--pccg"])) == ["pccg", "umart"]

    def test_every_active_retailer_has_a_scraper_module(self):
        """A retailer in ACTIVE_RETAILERS with no module would fail at runtime."""
        import importlib

        import run_daily

        for retailer in config.ACTIVE_RETAILERS:
            label, module = run_daily.SCRAPERS[retailer]
            assert label
            importlib.import_module(module)


class TestOldSnapshotsDoNotResurrectListings:
    """A stale JSON file must not undo a delisting.

    `find_or_create_listing` reactivates a listing whose exact URL turns up in
    a snapshot, on the reasoning that "we're scraping this URL live right now".
    That holds for today's file and not for a three-week-old one -- and
    CLAUDE.md makes a full re-ingest a *supported* operation ("the DB must be
    rebuildable from them via ingest.py"), so the unguarded version silently
    reverses every delisting the moment anyone rebuilds.

    Observed on 31-Aug-2026: a bare `python ingest.py` over the whole history
    flipped all 12 delisted and 11 stale Scorptec listings back to active.
    """

    def _db(self, tmp_path):
        import ingest

        db = tmp_path / "resurrect.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO products (category, brand, model, tracked) "
            "VALUES ('gpu', 'AMD', 'Radeon RX 6800', 1)"
        )
        conn.execute(
            "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
            "VALUES (1, 'scorptec', 'https://scorptec/6800', 'delisted')"
        )
        # It last had data on the 30th; the delisting happened after that.
        conn.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
            "VALUES (1, '2026-08-30', 799.0, 'in_stock')"
        )
        conn.commit()
        return conn

    def _status(self, conn):
        return conn.execute("SELECT status FROM retailer_listings WHERE id = 1").fetchone()[0]

    def test_an_older_snapshot_leaves_a_delisted_listing_alone(self, tmp_path):
        import ingest

        conn = self._db(tmp_path)
        ingest.find_or_create_listing(
            conn, 1, "scorptec", "https://scorptec/6800", snapshot_date="2026-08-20"
        )
        assert self._status(conn) == "delisted"
        conn.close()

    def test_todays_snapshot_still_relists_it(self, tmp_path):
        """A genuinely relisted product has to come back."""
        import ingest

        conn = self._db(tmp_path)
        ingest.find_or_create_listing(
            conn, 1, "scorptec", "https://scorptec/6800", snapshot_date="2026-08-31"
        )
        assert self._status(conn) == "active"
        conn.close()

    def test_the_same_days_snapshot_relists_it(self, tmp_path):
        """Re-ingesting the newest file must be idempotent, not a downgrade."""
        import ingest

        conn = self._db(tmp_path)
        ingest.find_or_create_listing(
            conn, 1, "scorptec", "https://scorptec/6800", snapshot_date="2026-08-30"
        )
        assert self._status(conn) == "active"
        conn.close()
