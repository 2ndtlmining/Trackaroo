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

from db.watchlist import load_all_rows, load_watchlist  # noqa: E402

PERF_INDEX_PATH = ROOT / "db" / "perf_index.json"

GPU_METRICS = ("gpu_raster_1440p", "gpu_rt_1440p")
CPU_METRICS = ("cpu_gaming_1080p",)
ALL_METRICS = GPU_METRICS + CPU_METRICS
METRIC_FIELDS = ("label", "unit", "source", "source_url", "as_of", "baseline")
REQUIRED_TIERS = ("current", "current-1")


def product_key(row: dict) -> str:
    """The index key for a watchlist row.

    GPU: the model when it already ends with its spec as a whole word
    ("GeForce RTX 5060 Ti 8GB" + "8GB"), otherwise "<model> <spec>".
    CPU: the model.
    """
    model = row["model"]
    if row["category"] != "gpu":
        return model
    spec = row["spec"].strip()
    if model.endswith(" " + spec):
        return model
    return f"{model} {spec}"


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


@pytest.fixture(scope="module")
def all_rows() -> dict:
    """Every watchlist row, retired included, keyed by its perf-index key.

    A retired product keeps its figures: its page and history stay, and a
    retirement can be undone without re-transcribing the chart.
    """
    return {product_key(r): r for r in load_all_rows(strict=True)}


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


def test_product_keys_match_watchlist(index, all_rows):
    stray = sorted(set(index["products"]) - set(all_rows))
    assert not stray, f"keys not in watchlist: {stray}"


def test_not_in_source_keys_match_watchlist(index, all_rows):
    for metric, keys in index["not_in_source"].items():
        assert metric in ALL_METRICS, metric
        assert len(keys) == len(set(keys)), f"duplicate in not_in_source[{metric}]"
        stray = sorted(set(keys) - set(all_rows))
        assert not stray, f"not_in_source[{metric}] keys not in watchlist: {stray}"


def test_metrics_match_category(index, all_rows):
    for key, values in index["products"].items():
        allowed = _metrics_for(all_rows[key]["category"])
        wrong = sorted(set(values) - set(allowed))
        assert not wrong, f"{key} has metrics for the other category: {wrong}"
    for metric, keys in index["not_in_source"].items():
        for key in keys:
            assert metric in _metrics_for(all_rows[key]["category"]), (key, metric)


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


def check_coverage(index: dict, watchlist: dict) -> None:
    """Fail on current/current-1 gaps; warn (UserWarning) on current-2 gaps.

    A gap is a (product, metric) pair with neither a value nor a
    not_in_source entry.
    """
    missing = _gaps(index, watchlist, REQUIRED_TIERS)
    assert not missing, f"no value and not in not_in_source: {missing}"
    optional = _gaps(index, watchlist, ("current-2",))
    if optional:
        warnings.warn(f"current-2 products without perf data: {optional}", UserWarning)


def test_coverage_of_real_data(index, watchlist):
    check_coverage(index, watchlist)


def _synthetic(tier: str):
    """A one-GPU watchlist with an index that has no data for it."""
    watchlist = {"Test GPU 8GB": {"category": "gpu", "model": "Test GPU", "spec": "8GB", "gen_tier": tier}}
    index = {"metrics": {}, "products": {}, "not_in_source": {}}
    return index, watchlist


def test_current2_gap_warns():
    index, watchlist = _synthetic("current-2")
    with pytest.warns(UserWarning, match="Test GPU 8GB"):
        check_coverage(index, watchlist)


@pytest.mark.parametrize("tier", REQUIRED_TIERS)
def test_required_tier_gap_fails(tier):
    index, watchlist = _synthetic(tier)
    with pytest.raises(AssertionError, match="Test GPU 8GB"):
        check_coverage(index, watchlist)


def test_not_in_source_closes_a_required_gap():
    index, watchlist = _synthetic("current")
    index["not_in_source"] = {m: ["Test GPU 8GB"] for m in GPU_METRICS}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        check_coverage(index, watchlist)


VRAM_VARIANT_KEYS = (
    "GeForce RTX 5060 Ti 16GB", "GeForce RTX 5060 Ti 8GB",
    "Radeon RX 9060 XT 16GB", "Radeon RX 9060 XT 8GB",
    "GeForce RTX 3050 8GB", "GeForce RTX 3050 6GB",
)


def test_vram_variants_are_separate_products(index, watchlist):
    """Each VRAM variant is its own key with its own values or not_in_source entry."""
    for key in VRAM_VARIANT_KEYS:
        assert key in watchlist, key
        values = index["products"].get(key, {})
        for metric in GPU_METRICS:
            in_products = metric in values
            in_nis = key in index["not_in_source"].get(metric, [])
            assert in_products != in_nis, (key, metric, in_products, in_nis)
    # The RT chart gives the two RTX 5060 Ti variants different values
    # ("16 GB: 35 %", "8 GB: 25 %"), which proves neither was copied.
    rt16 = index["products"]["GeForce RTX 5060 Ti 16GB"]["gpu_rt_1440p"]
    rt8 = index["products"]["GeForce RTX 5060 Ti 8GB"]["gpu_rt_1440p"]
    assert rt16 != rt8
    assert (rt16, rt8) == (35, 25)


@pytest.mark.parametrize(
    "model, spec, expected",
    [
        ("GeForce RTX 5060 Ti 8GB", "8GB", "GeForce RTX 5060 Ti 8GB"),
        ("Radeon RX 9060 XT 8GB", "8GB", "Radeon RX 9060 XT 8GB"),
        ("GeForce RTX 3050 6GB", "6GB", "GeForce RTX 3050 6GB"),
        ("GeForce RTX 5060 Ti", "16GB", "GeForce RTX 5060 Ti 16GB"),
        ("GeForce RTX 3050", "8GB", "GeForce RTX 3050 8GB"),
        # a suffix that is only part of a word is not the spec
        ("Radeon Example 16GB", "6GB", "Radeon Example 16GB 6GB"),
    ],
)
def test_gpu_product_key_rule(model, spec, expected):
    assert product_key({"category": "gpu", "model": model, "spec": spec}) == expected


def test_cpu_product_key_is_model():
    assert product_key({"category": "cpu", "model": "Core i5-14400F", "spec": "10c"}) == "Core i5-14400F"


def test_spec_suffixed_watchlist_rows_resolve(watchlist):
    for model in ("GeForce RTX 5060 Ti 8GB", "Radeon RX 9060 XT 8GB", "GeForce RTX 3050 6GB"):
        assert watchlist[model]["model"] == model
