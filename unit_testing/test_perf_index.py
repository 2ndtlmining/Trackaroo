"""
Tests for db/perf_index.json, the curated price-to-performance index (#33).

The index is hand-transcribed from one published chart per metric
(docs/perf-index-sources.md). These tests pin the shape and the honesty rules:

- every metric names its single source (title, https URL, YYYY-MM, baseline);
- every product key is a real watchlist key: "<model> <spec>" for GPUs,
  "<model>" for CPUs, so VRAM variants stay separate products;
- values are positive numbers, as published;
- every tracked current / current-1 product has its category's required
  metrics, or is listed under not_in_source for that metric (never estimated);
- a product is never both valued and listed as not_in_source for one metric;
- current-2 gaps are allowed, but reported as a warning.
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.watchlist import load_watchlist  # noqa: E402

PERF_INDEX_PATH = ROOT / "db" / "perf_index.json"

GPU_METRICS = ("gpu_raster_1440p", "gpu_rt_1440p")
CPU_METRICS = ("cpu_gaming_1080p",)
ALL_METRICS = GPU_METRICS + CPU_METRICS
METRIC_FIELDS = ("label", "unit", "source", "source_url", "as_of", "baseline")
REQUIRED_TIERS = ("current", "current-1")


def product_key(row: dict) -> str:
    """The index key for a watchlist row: '<model> <spec>' (GPU) or '<model>' (CPU)."""
    if row["category"] == "gpu":
        return f"{row['model']} {row['spec'].strip()}"
    return row["model"]


@pytest.fixture(scope="module")
def index() -> dict:
    with open(PERF_INDEX_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def watchlist() -> dict:
    """Watchlist rows keyed by their perf-index key."""
    rows = load_watchlist(strict=True)
    keyed = {product_key(r): r for r in rows}
    assert len(keyed) == len(rows), "two watchlist rows share a perf-index key"
    return keyed


def _metrics_for(category: str) -> tuple:
    return GPU_METRICS if category == "gpu" else CPU_METRICS


def test_top_level_shape(index):
    assert set(index) == {"metrics", "products", "not_in_source"}
    assert set(index["metrics"]) == set(ALL_METRICS)


@pytest.mark.parametrize("metric", ALL_METRICS)
def test_metric_has_single_named_source(index, metric):
    meta = index["metrics"][metric]
    for field in METRIC_FIELDS:
        assert isinstance(meta.get(field), str) and meta[field].strip(), f"{metric}.{field}"
    assert meta["unit"] == "relative %"
    assert meta["source_url"].startswith("https://"), meta["source_url"]
    assert re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", meta["as_of"]), meta["as_of"]


def test_product_keys_match_watchlist(index, watchlist):
    stray = sorted(set(index["products"]) - set(watchlist))
    assert not stray, f"keys not in watchlist: {stray}"


def test_not_in_source_keys_match_watchlist(index, watchlist):
    for metric, keys in index["not_in_source"].items():
        assert metric in ALL_METRICS, metric
        assert len(keys) == len(set(keys)), f"duplicate in not_in_source[{metric}]"
        stray = sorted(set(keys) - set(watchlist))
        assert not stray, f"not_in_source[{metric}] keys not in watchlist: {stray}"


def test_metrics_match_category(index, watchlist):
    for key, values in index["products"].items():
        allowed = _metrics_for(watchlist[key]["category"])
        wrong = sorted(set(values) - set(allowed))
        assert not wrong, f"{key} has metrics for the other category: {wrong}"
    for metric, keys in index["not_in_source"].items():
        for key in keys:
            assert metric in _metrics_for(watchlist[key]["category"]), (key, metric)


def test_values_are_positive_numbers(index):
    for key, values in index["products"].items():
        assert values, f"{key} has no values"
        for metric, value in values.items():
            assert isinstance(value, (int, float)) and not isinstance(value, bool), (key, metric)
            assert value > 0, (key, metric, value)


def test_never_both_valued_and_not_in_source(index):
    for metric, keys in index["not_in_source"].items():
        both = sorted(k for k in keys if metric in index["products"].get(k, {}))
        assert not both, f"{metric}: valued and not_in_source: {both}"


def _gaps(index, watchlist, tiers):
    """(key, metric) pairs with neither a value nor a not_in_source entry."""
    missing = []
    for key, row in watchlist.items():
        if row["gen_tier"] not in tiers:
            continue
        for metric in _metrics_for(row["category"]):
            if metric in index["products"].get(key, {}):
                continue
            if key in index["not_in_source"].get(metric, []):
                continue
            missing.append((key, metric))
    return sorted(missing)


def test_tracked_current_and_current1_are_covered(index, watchlist):
    missing = _gaps(index, watchlist, REQUIRED_TIERS)
    assert not missing, f"no value and not in not_in_source: {missing}"


def test_vram_variants_are_separate_products(index, watchlist):
    """RTX 5060 Ti 8GB/16GB and RX 9060 XT 8GB/16GB resolve to distinct keys."""
    for key in ("GeForce RTX 5060 Ti 16GB", "GeForce RTX 5060 Ti 8GB 8GB",
                "Radeon RX 9060 XT 16GB", "Radeon RX 9060 XT 8GB 8GB"):
        assert key in watchlist, key


def test_current2_gaps_warn(index, watchlist):
    missing = _gaps(index, watchlist, ("current-2",))
    if missing:
        warnings.warn(f"current-2 products without perf data: {missing}", UserWarning)
