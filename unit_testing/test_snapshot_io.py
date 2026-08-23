"""Tests for scraper.snapshot_io — the atomic, no-downgrade snapshot writer.

The bug these guard against: a rate-limited PCCG re-run that matched zero
products overwrote the complete snapshot taken earlier the same day, losing
165 snapshots across 19-Aug and 21-Aug 2026.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from scraper.snapshot_io import (
    build_snapshot,
    read_snapshot,
    save_snapshot,
    snapshot_size,
)


def make(products, unmatched=None, retailer="pccg", category="gpu"):
    return build_snapshot(
        retailer=retailer,
        scrape_date="23_August_2026",
        category=category,
        total_watchlist=100,
        products=[{"url": f"https://x/{i}", "price_aud": i} for i in range(products)],
        unmatched_models=unmatched or [],
    )


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


# ── build_snapshot ────────────────────────────────────────────────────────

def test_build_snapshot_shape_matches_the_scraper_envelope():
    snap = make(3, unmatched=["RTX 4090"])
    assert set(snap) == {
        "retailer", "scrape_date", "category", "total_watchlist",
        "matched", "unmatched_count", "unmatched_models", "products",
    }
    assert snap["matched"] == 3
    assert snap["unmatched_count"] == 1


# ── snapshot_size ─────────────────────────────────────────────────────────

def test_snapshot_size_prefers_products_length():
    # A hand-edited file whose `matched` disagrees with `products` is sized
    # by what it actually holds, so the guard can't be fooled by the header.
    assert snapshot_size({"matched": 99, "products": [1, 2]}) == 2


def test_snapshot_size_falls_back_to_matched_then_zero():
    assert snapshot_size({"matched": 7}) == 7
    assert snapshot_size({}) == 0


# ── read_snapshot ─────────────────────────────────────────────────────────

def test_read_snapshot_returns_none_for_missing_or_corrupt(tmp_path):
    assert read_snapshot(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert read_snapshot(bad) is None


# ── save_snapshot: the happy path ─────────────────────────────────────────

def test_save_snapshot_writes_a_new_file(tmp_path):
    target = tmp_path / "gpu_pccg_23_August_2026.json"
    written = save_snapshot(target, make(5))

    assert written == target
    assert json.loads(target.read_text(encoding="utf-8"))["matched"] == 5


def test_save_snapshot_creates_missing_parent_dirs(tmp_path):
    target = tmp_path / "deep" / "nested" / "snap.json"
    save_snapshot(target, make(1))
    assert target.exists()


def test_save_snapshot_leaves_no_tmp_file_behind(tmp_path):
    target = tmp_path / "snap.json"
    save_snapshot(target, make(2))
    assert list(tmp_path.glob("*.tmp")) == []


# ── save_snapshot: the no-downgrade guard ─────────────────────────────────

def test_a_richer_snapshot_replaces_a_poorer_one(tmp_path):
    target = tmp_path / "snap.json"
    save_snapshot(target, make(10))
    written = save_snapshot(target, make(20))

    assert written == target
    assert snapshot_size(read_snapshot(target)) == 20


def test_an_equal_sized_snapshot_still_replaces(tmp_path):
    # A same-size re-run is a legitimate refresh (prices may have changed),
    # so only a strictly smaller result is diverted.
    target = tmp_path / "snap.json"
    save_snapshot(target, make(10))
    written = save_snapshot(target, make(10))
    assert written == target


def test_an_empty_rerun_cannot_destroy_a_good_snapshot(tmp_path):
    """The exact 19-Aug / 21-Aug PCCG regression."""
    target = tmp_path / "gpu_pccg_23_August_2026.json"
    save_snapshot(target, make(102))

    written = save_snapshot(target, make(0), timestamp=datetime(2026, 8, 23, 4, 5, 6))

    # The good file is untouched...
    assert snapshot_size(read_snapshot(target)) == 102
    # ...and the failed run is parked, not silently dropped.
    assert written == tmp_path / "gpu_pccg_23_August_2026.partial-040506.json"
    assert snapshot_size(read_snapshot(written)) == 0


def test_a_partial_rerun_is_diverted_to_a_sidecar(tmp_path):
    target = tmp_path / "snap.json"
    save_snapshot(target, make(100))
    written = save_snapshot(target, make(11), timestamp=datetime(2026, 8, 23, 1, 2, 3))

    assert written.name == "snap.partial-010203.json"
    assert snapshot_size(read_snapshot(target)) == 100


def test_the_guard_warns_so_a_downgrade_is_never_silent(tmp_path, caplog):
    target = tmp_path / "snap.json"
    save_snapshot(target, make(50))
    with caplog.at_level("WARNING"):
        save_snapshot(target, make(0))
    assert "Refusing to overwrite" in caplog.text


def test_a_corrupt_existing_file_does_not_block_a_good_write(tmp_path):
    # An unreadable leftover is treated as absent — otherwise a truncated file
    # from the old non-atomic writer would wedge the scraper forever.
    target = tmp_path / "snap.json"
    target.write_text("{truncated", encoding="utf-8")
    written = save_snapshot(target, make(7))

    assert written == target
    assert snapshot_size(read_snapshot(target)) == 7


# ── save_snapshot: atomicity ──────────────────────────────────────────────

def test_a_failed_write_leaves_the_previous_snapshot_intact(tmp_path, monkeypatch):
    target = tmp_path / "snap.json"
    save_snapshot(target, make(10))

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("scraper.snapshot_io.json.dump", boom)
    with pytest.raises(OSError):
        save_snapshot(target, make(20))

    # The old snapshot survived and no .tmp debris remains.
    assert snapshot_size(read_snapshot(target)) == 10
    assert list(tmp_path.glob("*.tmp")) == []
