"""Boot order seed -> migrate -> ingest keeps retired products untracked (#18)."""
import sqlite3

import ingest
import seed
from config import SCHEMA_PATH


def test_ingest_after_seed_keeps_retired_product_untracked(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "fresh.db"))
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    seed.seed_products(conn, [{"category": "gpu", "brand": "AMD", "model": "Radeon RX 9070 XTX",
                               "vram_gb": 32, "cores": None, "generation_tier": "current",
                               "tracked": 0, "series": "rx9000"}])
    pid = ingest.find_or_create_product(conn, {"watchlist_category": "gpu", "watchlist_brand": "AMD",
                                               "watchlist_model": "Radeon RX 9070 XTX",
                                               "watchlist_gen_tier": "current"})
    assert conn.execute("SELECT tracked FROM products WHERE id = ?", (pid,)).fetchone()[0] == 0
