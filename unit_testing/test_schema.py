"""
Tests for the SQLite schema — constraints, triggers, and data integrity.

Verifies that:
- CHECK constraints work (invalid values are rejected)
- The last_snapshot_at trigger fires correctly
- Foreign key constraints are enforced
- Unique constraints prevent duplicate snapshots
"""
import sqlite3

import pytest


class TestProductConstraints:
    """Test products table CHECK constraints."""

    def test_invalid_category_rejected(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO products (category, brand, model) VALUES ('motherboard', 'ASUS', 'ROG')"
            )

    def test_valid_category_cpu(self, db):
        db.execute(
            "INSERT INTO products (category, brand, model) VALUES ('cpu', 'AMD', 'Ryzen 7')"
        )
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1

    def test_valid_category_gpu(self, db):
        db.execute(
            "INSERT INTO products (category, brand, model) VALUES ('gpu', 'NVIDIA', 'RTX 5070')"
        )
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1

    def test_invalid_generation_tier_rejected(self, db):
        db.execute(
            "INSERT INTO products (category, brand, model) VALUES ('cpu', 'AMD', 'Ryzen 7')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE products SET generation_tier = 'current-3' WHERE model = 'Ryzen 7'"
            )

    def test_valid_generation_tiers(self, db):
        db.execute(
            "INSERT INTO products (category, brand, model, generation_tier) VALUES "
            "('cpu', 'AMD', 'Ryzen 5', 'current'), "
            "('cpu', 'AMD', 'Ryzen 5 old', 'current-1'), "
            "('cpu', 'AMD', 'Ryzen 5 older', 'current-2')"
        )
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 3


class TestRetailerListingConstraints:
    """Test retailer_listings table constraints."""

    def _insert_product(self, db):
        db.execute(
            "INSERT INTO products (category, brand, model) VALUES ('gpu', 'NVIDIA', 'RTX 5070')"
        )
        return db.execute("SELECT id FROM products WHERE model = 'RTX 5070'").fetchone()[0]

    def test_invalid_retailer_rejected(self, db):
        pid = self._insert_product(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url) "
                "VALUES (?, 'amazon', 'https://amazon.com/test')",
                (pid,),
            )

    def test_valid_retailer(self, db):
        pid = self._insert_product(db)
        db.execute(
            "INSERT INTO retailer_listings (product_id, retailer, listing_url) "
            "VALUES (?, 'scorptec', 'https://scorptec.com.au/test')",
            (pid,),
        )
        assert db.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0] == 1

    def test_invalid_status_rejected(self, db):
        pid = self._insert_product(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                "VALUES (?, 'pccg', 'https://pccg.com/test', 'removed')",
                (pid,),
            )

    def test_valid_statuses(self, db):
        pid = self._insert_product(db)
        for status in ("active", "delisted", "stale"):
            db.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url, status) "
                "VALUES (?, 'scorptec', 'https://scorptec.com/test_" + status + "', ?)",
                (pid, status),
            )
        assert db.execute("SELECT COUNT(*) FROM retailer_listings").fetchone()[0] == 3

    def test_unique_retailer_url(self, db):
        pid = self._insert_product(db)
        url = "https://scorptec.com.au/products/12345/test-product"
        db.execute(
            "INSERT INTO retailer_listings (product_id, retailer, listing_url) VALUES (?, 'scorptec', ?)",
            (pid, url),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url) VALUES (?, 'scorptec', ?)",
                (pid, url),
            )

    def test_fk_product_must_exist(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO retailer_listings (product_id, retailer, listing_url) "
                "VALUES (99999, 'scorptec', 'https://scorptec.com/test')"
            )


class TestPriceSnapshotConstraints:
    """Test price_snapshots table constraints."""

    def _setup(self, db):
        """Insert a product and a listing, return the listing ID."""
        db.execute(
            "INSERT INTO products (category, brand, model) VALUES ('cpu', 'AMD', 'Ryzen 7')"
        )
        pid = db.execute("SELECT id FROM products WHERE model = 'Ryzen 7'").fetchone()[0]
        db.execute(
            "INSERT INTO retailer_listings (product_id, retailer, listing_url) "
            "VALUES (?, 'scorptec', 'https://scorptec.com.au/test')",
            (pid,),
        )
        lid = db.execute("SELECT id FROM retailer_listings WHERE product_id = ?", (pid,)).fetchone()[0]
        return lid

    def test_invalid_stock_status_rejected(self, db):
        lid = self._setup(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                "VALUES (?, '2026-08-10', 500.0, 'sold_out')",
                (lid,),
            )

    def test_valid_stock_statuses(self, db):
        lid = self._setup(db)
        dates = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"]
        for status, d in zip(("in_stock", "out_of_stock", "preorder", "unknown"), dates):
            db.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                "VALUES (?, ?, 500.0, ?)",
                (lid, d, status),
            )
        assert db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == 4

    def test_duplicate_date_rejected(self, db):
        lid = self._setup(db)
        db.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud) "
            "VALUES (?, '2026-08-10', 500.0)",
            (lid,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud) "
                "VALUES (?, '2026-08-10', 550.0)",
                (lid,),
            )

    def test_fk_listing_must_exist(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud) "
                "VALUES (99999, '2026-08-10', 500.0)"
            )


class TestTriggers:
    """Test the last_snapshot_at trigger."""

    def _setup_with_snapshot(self, db):
        """Full setup: product → listing → snapshot."""
        db.execute(
            "INSERT INTO products (category, brand, model) VALUES ('gpu', 'NVIDIA', 'RTX 5070')"
        )
        pid = db.execute("SELECT id FROM products WHERE model = 'RTX 5070'").fetchone()[0]
        db.execute(
            "INSERT INTO retailer_listings (product_id, retailer, listing_url) "
            "VALUES (?, 'pccg', 'https://pccg.com/test')",
            (pid,),
        )
        lid = db.execute("SELECT id FROM retailer_listings WHERE product_id = ?", (pid,)).fetchone()[0]
        db.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, scraped_at) "
            "VALUES (?, '2026-08-10', 999.0, '2026-08-10T12:00:00Z')",
            (lid,),
        )
        return pid, lid

    def test_listing_last_snapshot_updated(self, db):
        _, lid = self._setup_with_snapshot(db)
        row = db.execute(
            "SELECT last_snapshot_at FROM retailer_listings WHERE id = ?", (lid,)
        ).fetchone()
        assert row[0] == "2026-08-10T12:00:00Z"

    def test_product_last_snapshot_updated(self, db):
        pid, _ = self._setup_with_snapshot(db)
        row = db.execute(
            "SELECT last_snapshot_at FROM products WHERE id = ?", (pid,)
        ).fetchone()
        assert row[0] == "2026-08-10T12:00:00Z"

    def test_listing_last_seen_updated(self, db):
        _, lid = self._setup_with_snapshot(db)
        row = db.execute(
            "SELECT last_seen_at FROM retailer_listings WHERE id = ?", (lid,)
        ).fetchone()
        assert row[0] == "2026-08-10T12:00:00Z"

    def test_product_last_snapshot_keeps_newest(self, db):
        pid, lid = self._setup_with_snapshot(db)
        # Insert a newer snapshot
        db.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, scraped_at) "
            "VALUES (?, '2026-08-11', 950.0, '2026-08-11T12:00:00Z')",
            (lid,),
        )
        row = db.execute(
            "SELECT last_snapshot_at FROM products WHERE id = ?", (pid,)
        ).fetchone()
        assert row[0] == "2026-08-11T12:00:00Z"

    def test_product_last_snapshot_not_rolled_back(self, db):
        pid, lid = self._setup_with_snapshot(db)
        # Insert an older snapshot (should not roll back)
        db.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, scraped_at) "
            "VALUES (?, '2026-08-09', 1050.0, '2026-08-09T12:00:00Z')",
            (lid,),
        )
        row = db.execute(
            "SELECT last_snapshot_at FROM products WHERE id = ?", (pid,)
        ).fetchone()
        assert row[0] == "2026-08-10T12:00:00Z"  # Still the newer one
