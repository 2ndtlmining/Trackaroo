"""
Shared fixtures for the Trackaroo test suite.

Provides an isolated in-memory SQLite database with the full schema,
so tests don't touch the production DB.
"""
import os
import socket
import sqlite3
import tempfile
import types
from pathlib import Path

import pytest

# Path to the schema SQL
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

# ── No real network, ever (#13) ──────────────────────────────────────
# Tests must mock HTTP. Any connect() to a non-loopback address fails loudly
# naming the address, so a test that would have scraped a retailer (or posted
# to Discord from a developer's .env) cannot pass by accident. Loopback stays
# open for tests that run a local server; AF_UNIX is untouched.
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_LOOPBACK = ("127.", "::1", "localhost")


def _is_blocked(self, address):
    return self.family in (socket.AF_INET, socket.AF_INET6) and not str(address[0]).startswith(
        _LOOPBACK
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def guarded(self, address):
        if _is_blocked(self, address):
            raise RuntimeError(f"Blocked outbound connection to {address!r}: tests must mock HTTP")
        return _REAL_CONNECT(self, address)

    def guarded_ex(self, address):
        if _is_blocked(self, address):
            raise RuntimeError(f"Blocked outbound connection to {address!r}: tests must mock HTTP")
        return _REAL_CONNECT_EX(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_ex)


# ── No real off-host backup mirror, ever (#10 F17/I4) ──────────────────
# backup_db.backup_database() falls back to config.BACKUP_MIRROR_DIR when no
# mirror_dir is given, so ANY test that calls it (directly or through
# run_daily) would silently copy a test backup to a real NAS mount if the
# developer's shell happens to have TRACKAROO_BACKUP_MIRROR_DIR set. Autouse
# and global -- not just in test_backup.py -- so every test is covered,
# including ones (like test_restore_drill.py) that pass mirror_dir=None and
# rely on that meaning "off" rather than "read the environment".
@pytest.fixture(autouse=True)
def _no_real_backup_mirror(monkeypatch):
    monkeypatch.setattr("backup_db.BACKUP_MIRROR_DIR", None)


# discover.run() defaults to the real DB and the real data/catalogue (it creates
# tables, writes a discovery_runs row and prunes old catalogues). Any test that
# reaches it without passing paths (e.g. run_daily.main() without the
# isolated_pipeline fixture) must hit throwaway paths instead.
@pytest.fixture(autouse=True)
def _no_real_discovery_paths(monkeypatch, tmp_path):
    import discover
    monkeypatch.setattr(discover, "DB_PATH", tmp_path / "discover-guard.db")
    monkeypatch.setattr(discover, "DATA_DIR", tmp_path / "discover-guard-data")


def _make_connection(use_memory: bool = True) -> sqlite3.Connection:
    """Create a fresh connection with the schema applied."""
    if use_memory:
        conn = sqlite3.connect(":memory:")
    else:
        # File-based temp DB for tests that need persistence across connections
        fd, path = tempfile.mkstemp(suffix=".db")
        conn = sqlite3.connect(path)
        os.close(fd)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row  # Enable named column access in tests
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


@pytest.fixture
def db():
    """Fresh in-memory SQLite DB with the Trackaroo schema."""
    conn = _make_connection(use_memory=True)
    yield conn
    conn.close()


@pytest.fixture
def db_path(tmp_path):
    """File-based temp DB path that persists across separate connections."""
    path = tmp_path / "test_trackaroo.db"
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return path


# ── Sample product data ──────────────────────────────────────────────

@pytest.fixture
def sample_cpu():
    """A sample CPU product dict matching watchlist.csv format."""
    return {
        "category": "cpu",
        "brand": "AMD",
        "model": "Ryzen 7 9800X3D",
        "vram_gb": None,
        "cores": 8,
        "generation_tier": "current",
        "tracked": 1,
    }


@pytest.fixture
def sample_gpu():
    """A sample GPU product dict matching watchlist.csv format."""
    return {
        "category": "gpu",
        "brand": "NVIDIA",
        "model": "GeForce RTX 5070 Ti",
        "vram_gb": 16,
        "cores": None,
        "generation_tier": "current",
        "tracked": 1,
    }


@pytest.fixture
def sample_snapshot():
    """A sample price snapshot dict."""
    return {
        "snapshot_date": "2026-08-10",
        "price_aud": 999.0,
        "stock_status": "in_stock",
    }


# ── run_daily end-to-end harness ─────────────────────────────────────

@pytest.fixture
def isolated_pipeline(monkeypatch, tmp_path):
    """Run ``run_daily.run()`` end to end with every side effect faked.

    The DB is a real file DB (so several connections see the same rows), the
    data dir is a temp dir, and the digest, alerts, price alerts, delisted
    check, JSON mirror and backup are recorded instead of performed. Each test
    still chooses what the scrapers return by patching ``run_daily.run_scraper``.
    Health checks are off by default (``run_db_checks`` / ``check_json_files``
    return nothing); a test that wants one re-patches it.
    """
    import run_daily

    calls = types.SimpleNamespace(
        alerts=[], discovery_runs=[], digests=0, price_alert_runs=0, backups=0, delisted_runs=0, heartbeats=0,
        db_path=tmp_path / "pipeline.db", data_dir=tmp_path / "data",
    )
    calls.data_dir.mkdir()
    conn = sqlite3.connect(str(calls.db_path))
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()

    def fake_init_db(path):
        c = sqlite3.connect(str(calls.db_path))
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def fake_digest(*a, **k):
        calls.digests += 1
        return 1  # notify_discord.run() returns an embed count; 1 == "delivered" (fix-round-1 I1).

    def fake_price_alerts(*a, **k):
        calls.price_alert_runs += 1

    def fake_backup(**k):
        calls.backups += 1

    def fake_delisted(*a, **k):
        calls.delisted_runs += 1

    monkeypatch.setattr(run_daily, "init_db", fake_init_db)
    monkeypatch.setattr(run_daily, "DB_PATH", calls.db_path)
    monkeypatch.setattr(run_daily, "DATA_DIR", calls.data_dir)
    monkeypatch.setattr(run_daily, "SCRAPER_GAP_SECONDS", 0)
    monkeypatch.setattr(run_daily, "check_json_files", lambda *a, **k: [])
    monkeypatch.setattr(run_daily, "run_db_checks", lambda *a, **k: [])
    monkeypatch.setattr("export_snapshots.run", lambda **k: {"recovered": 0, "written": 0})
    monkeypatch.setattr("check_delisted.run", fake_delisted)
    monkeypatch.setattr("check_stale_listings.run", lambda *a, **k: None)
    monkeypatch.setattr("notify_discord.run", fake_digest)
    monkeypatch.setattr(
        "notify_discord.send_alert",
        lambda lines, dry_run=False: calls.alerts.append(list(lines)) or 1,
    )
    monkeypatch.setattr("check_alerts.run", fake_price_alerts)
    monkeypatch.setattr("discover.run", lambda **k: calls.discovery_runs.append(k) or {})
    monkeypatch.setattr("backup_db.backup_database", fake_backup)

    def fake_ping(*a, **k):
        calls.heartbeats += 1
        return True

    monkeypatch.setattr("heartbeat.ping", fake_ping)
    return calls
