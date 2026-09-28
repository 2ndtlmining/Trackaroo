"""The chip-key matcher: one rule for "is this listing that product" (#1, #2)."""
import csv
from pathlib import Path

import pytest

from db.watchlist import load_watchlist
from scraper.chip_key import Matcher, chip_key, is_excluded, normalise, parse_vram

FIXTURE = Path(__file__).parent / "fixtures" / "titles.csv"


def _corpus():
    with FIXTURE.open(encoding="utf-8") as fh:
        return [(r["category"], r["title"], r["expected"] or None) for r in csv.DictReader(fh)]


@pytest.fixture(scope="module")
def matcher():
    return Matcher(load_watchlist(strict=True))


@pytest.mark.parametrize("category,title,expected", _corpus())
def test_corpus(matcher, category, title, expected):
    idx = matcher.resolve(title, category)
    got = matcher.watchlist[idx]["model"] if idx is not None else None
    assert got == expected, f"{title!r}: expected {expected!r}, got {got!r}"


def test_every_watchlist_row_has_a_key_and_no_collisions(matcher):
    assert matcher.collisions() == []


def test_every_watchlist_row_matches_its_own_model_name(matcher):
    """A row that cannot match its own name can never match a listing."""
    missed = [
        wp["model"]
        for i, wp in enumerate(matcher.watchlist)
        if matcher.resolve(f"{wp['model']} {wp['vram_gb'] or ''}GB", wp["category"]) != i
        and matcher.resolve(wp["model"], wp["category"]) != i
    ]
    assert missed == []


@pytest.mark.parametrize("raw,norm", [
    ("RTX5070Ti", "rtx5070ti"),
    ("i5-14400F", "i5 14400f"),
    ("Ryzen 7 5800X3D,", "ryzen 7 5800x3d"),
])
def test_normalise(raw, norm):
    assert normalise(raw) == norm


@pytest.mark.parametrize("text,category,key", [
    ("rtx5070ti", "gpu", "rtx 5070 ti"),
    ("RTX 4070 Ti SUPER", "gpu", "rtx 4070 ti super"),
    ("Radeon RX 9070GRE", "gpu", "rx 9070 gre"),
    ("rx 7900 xtx", "gpu", "rx 7900 xtx"),
    ("Arc B580", "gpu", "arc b580"),
    ("Ryzen 5 5500GT", "cpu", "ryzen 5500gt"),
    ("R7 5800X3D", "cpu", "ryzen 5800x3d"),
    ("Core Ultra 7 270K Plus", "cpu", "ultra 270k plus"),
    ("Core i9-14900KS", "cpu", "core 14900ks"),
    ("RTX 5090", "cpu", None),          # category restricts the patterns
    ("Samsung 990 Pro 2TB", "gpu", None),
])
def test_chip_key(text, category, key):
    assert chip_key(text, category) == key


@pytest.mark.parametrize("text,vram", [
    ("dual 8g", 8), ("16GB GDDR7", 16), ("32g, 32gb", 32), ("no memory here", None), ("gddr7", None),
    ("o16g", 16),
])
def test_parse_vram(text, vram):
    assert parse_vram(text) == vram


@pytest.mark.parametrize("text", ["AORUS RTX 5090 AI BOX", "eGPU dock", "Gaming Laptop RTX 5070", "CPU bundle"])
def test_is_excluded(text):
    assert is_excluded(text)


def test_multi_vram_line_without_vram_is_unmatched(matcher):
    assert matcher.resolve("Gigabyte GeForce RTX 5060 Ti Eagle OC", "gpu") is None


def test_vram_falls_back_to_extra_text(matcher):
    idx = matcher.resolve("Gigabyte GeForce RTX 5060 Ti Eagle OC", "gpu", extra_text="8GB GDDR7 memory")
    assert matcher.watchlist[idx]["model"] == "GeForce RTX 5060 Ti 8GB"
