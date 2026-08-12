"""
Concurrent read/write tests for the Trackaroo database.

Verifies that SQLite under WAL mode handles a writer (the cron-driven
run_daily.py) writing snapshots while readers (the future frontend) query,
without "database is locked" (sqlite3.OperationalError) failures.

Why this matters: the frontend will read db/trackaroo.db while run_daily.py
writes to it on a schedule. WAL is what makes concurrent reads safe — this
test proves it, and its first test asserts WAL is actually enabled.
"""
import sqlite3
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, sys_path)

from query import get_connection, show_latest_prices, show_trends
from ingest import init_db

WRITER_ITERATIONS = 30
SNAPSHOTS_PER_BATCH = 10
READER_THREADS = 3


class TestWALEnabled:
    """WAL is established by the writer path and inherited by readers."""

    def test_writer_init_puts_file_in_wal(self, db_path):
        """init_db (the scrape/ingest writer path) flips a file DB to WAL."""
        conn = init_db(db_path)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            conn.close()

        # Mode persists in the DB file header even after close.
        raw = sqlite3.connect(str(db_path))
        try:
            assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            raw.close()

    def test_reader_inherits_wal(self, db_path):
        """Opening for reads preserves an existing WAL mode (never downgrades)."""
        init_db(db_path).close()

        conn = get_connection(db_path)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            conn.close()


class TestConcurrentReadWrite:
    """A writer thread appending snapshots while reader threads query."""

    def _seed_listing(self, db_path, model="RTX Concurrent 5090"):
        """Insert one product + one listing to write snapshots to."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO products (category, brand, model, tracked) VALUES ('gpu', 'NVIDIA', ?, 1)",
            (model,),
        )
        product_id = conn.execute(
            "SELECT id FROM products WHERE model = ?", (model,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status) "
            "VALUES (?, 'scorptec', 'Test Variant', 'https://x.com/concurrent', 'active')",
            (product_id,),
        )
        listing_id = conn.execute(
            "SELECT id FROM retailer_listings WHERE listing_url = 'https://x.com/concurrent'"
        ).fetchone()[0]
        conn.commit()
        conn.close()
        return listing_id

    def _writer(self, db_path, listing_id, done, errors):
        """Append snapshot batches in explicit transactions with a pause before commit."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        base_date = date(2026, 9, 1)
        try:
            for i in range(WRITER_ITERATIONS):
                # Explicit transaction keeps the write window open while
                # readers pound the DB — the scenario that would raise
                # SQLITE_BUSY under a non-WAL journal mode.
                conn.execute("BEGIN")
                for j in range(SNAPSHOTS_PER_BATCH):
                    snapshot_date = (
                        base_date + timedelta(days=i * SNAPSHOTS_PER_BATCH + j)
                    ).strftime("%Y-%m-%d")
                    conn.execute(
                        "INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) "
                        "VALUES (?, ?, ?, 'in_stock')",
                        (listing_id, snapshot_date, 100.0 + i),
                    )
                time.sleep(0.005)  # Widen the uncommitted window
                conn.commit()
        except sqlite3.Error as e:  # noqa: BLE001 - record any DB failure
            errors.append(f"writer: {e}")
        finally:
            conn.close()
            done.set()

    def _reader(self, db_path, done, errors):
        """Run both query tools repeatedly until the writer signals done."""
        try:
            conn = get_connection(db_path)
        except sqlite3.Error as e:
            errors.append(f"reader({threading.current_thread().name}) connect: {e}")
            return
        try:
            # Short busy timeout: if a read ever had to wait on a write lock,
            # it would time out and raise rather than silently pass.
            conn.execute("PRAGMA busy_timeout=100")
            while not done.is_set():
                try:
                    show_latest_prices(conn)
                    show_trends(conn)
                except sqlite3.Error as e:
                    errors.append(f"reader({threading.current_thread().name}): {e}")
                time.sleep(0.001)
        finally:
            conn.close()

    def test_reads_during_writes_no_lock_errors(self, db_path):
        """Readers must never hit 'database is locked' while a writer commits."""
        # Real-world precondition: run_daily already set WAL on this file.
        init_db(db_path).close()
        listing_id = self._seed_listing(db_path)

        done = threading.Event()
        errors: list[str] = []

        writer = threading.Thread(
            target=self._writer, args=(db_path, listing_id, done, errors), name="writer"
        )
        readers = [
            threading.Thread(
                target=self._reader, args=(db_path, done, errors), name=f"reader-{i}"
            )
            for i in range(READER_THREADS)
        ]

        for t in readers:
            t.start()
        writer.start()
        for t in readers + [writer]:
            t.join(timeout=60)

        assert not writer.is_alive(), "writer thread did not finish"

        assert errors == [], f"concurrency errors: {errors}"

        # Every writer batch landed — nothing lost to lock contention.
        count = sqlite3.connect(str(db_path)).execute(
            "SELECT COUNT(*) FROM price_snapshots"
        ).fetchone()[0]
        assert count == WRITER_ITERATIONS * SNAPSHOTS_PER_BATCH