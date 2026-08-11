"""
Shared fixtures for the Trackaroo test suite.

Provides an isolated in-memory SQLite database with the full schema,
so tests don't touch the production DB.
"""
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Path to the schema SQL
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


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
