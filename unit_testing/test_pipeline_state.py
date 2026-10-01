"""Bookkeeping tables the pipeline and the dashboard share (R1, #8, R3)."""
import sqlite3

from config import ACTIVE_RETAILERS
from migrate import check_table_exists
from pipeline_state import ensure_ops_tables, sync_active_retailers


def _legacy(tmp_path):
    """A DB from before this phase: no bookkeeping tables at all."""
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
    return conn


class TestActiveRetailers:
    def test_sync_writes_the_config_list_in_order(self, db):
        sync_active_retailers(db, ACTIVE_RETAILERS)
        rows = db.execute("SELECT retailer FROM active_retailers ORDER BY position").fetchall()
        assert [r[0] for r in rows] == list(ACTIVE_RETAILERS)

    def test_sync_replaces_rather_than_appends(self, db):
        sync_active_retailers(db, ["scorptec", "pccg", "umart"])
        sync_active_retailers(db, ["scorptec", "umart"])
        rows = db.execute("SELECT retailer, position FROM active_retailers ORDER BY position").fetchall()
        assert [tuple(r) for r in rows] == [("scorptec", 0), ("umart", 1)]

    def test_works_on_a_db_that_predates_the_table(self, tmp_path):
        conn = _legacy(tmp_path)
        sync_active_retailers(conn, ["umart"])
        assert conn.execute("SELECT retailer FROM active_retailers").fetchall() == [("umart",)]

    def test_ensure_is_idempotent(self, tmp_path):
        conn = _legacy(tmp_path)
        ensure_ops_tables(conn)
        ensure_ops_tables(conn)
        assert check_table_exists(conn, "active_retailers")
