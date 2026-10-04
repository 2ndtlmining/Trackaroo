# unit_testing/test_discover_rules.py
"""Pure classification rules for discovery (#16)."""
import pytest

import discover_rules as r
from db.watchlist import load_watchlist
from scraper.chip_key import chip_key


@pytest.mark.parametrize("title", [
    "Gigabyte Z890 Ultra 5 Power Bundle", "Gigabyte Aorus RTX 5090 AI Box", "ASUS ROG laptop RTX 5070",
    "Refurbished RTX 4070", "PNY NVIDIA RTX PRO 6000 Blackwell", "AMD Radeon Pro W7800",
    "AMD Ryzen Threadripper 7980X", "Intel Xeon w5-2455X", "AMD EPYC 9654", "Open Box RTX 5080",
])
def test_excluded_titles(title):
    assert r.is_excluded_title(title)


def test_plain_card_not_excluded():
    assert not r.is_excluded_title("MSI GeForce RTX 5050 Ventus 2X OC 8G")


@pytest.mark.parametrize("category,key,tier", [
    ("gpu", "rtx 5050", "current"), ("gpu", "rtx 4060 ti", "current-1"), ("gpu", "rtx 3050", "current-2"),
    ("gpu", "rtx 2060", None), ("gpu", "rtx 6070", "current"),
    ("gpu", "rx 9070 gre", "current"), ("gpu", "rx 7600 xt", "current-1"), ("gpu", "rx 6600", "current-2"),
    ("gpu", "rx 5700 xt", None), ("gpu", "arc b580", "current"), ("gpu", "arc a750", "current-1"),
    ("cpu", "ryzen 9950x3d2", "current"), ("cpu", "ryzen 8600g", "current-1"), ("cpu", "ryzen 7700x3d", "current-1"),
    ("cpu", "ryzen 5600gt", "current-2"), ("cpu", "ryzen 3600", None),
    ("cpu", "ultra 270k plus", "current"), ("cpu", "ultra 225f", "current"), ("cpu", "ultra 155h", None),
    ("cpu", "core 14600kf", "current-1"), ("cpu", "core 13400", "current-2"), ("cpu", "core 12400f", None),
])
def test_series_tier(category, key, tier):
    assert r.series_tier(category, key) == tier


@pytest.mark.parametrize("title", [
    "Leadtek NVIDIA RTX 6000 Ada Generation 48GB", "PNY RTX 4000 SFF Ada Generation 20GB",
    "RTX 5000 Ada 32GB", "RTX 4500 Ada", "RTX 5880 Ada", "RTX 2000 Ada",
])
def test_nvidia_workstation_cards_are_out_of_scope(title):
    assert r.series_tier("gpu", chip_key(title, "gpu")) is None


@pytest.mark.parametrize("key", ["rtx 5050", "rtx 6070", "rtx 3090 ti", "rtx 4090"])
def test_consumer_geforce_numbers_stay_in_scope(key):
    assert r.series_tier("gpu", key) is not None


def test_every_watchlist_row_is_in_scope_at_its_own_tier():
    # The scope table must agree with db/watchlist.csv (and so ARCHITECTURE Part 2).
    for wp in load_watchlist():
        key = chip_key(wp["model"], wp["category"])
        assert r.series_tier(wp["category"], key) == wp["gen_tier"], wp["model"]


def test_part_key():
    assert r.part_key("gpu", "rtx 5050", 8) == "rtx 5050|8"
    assert r.part_key("gpu", "rtx 5050", None) == "rtx 5050"
    assert r.part_key("cpu", "ryzen 5600gt", None) == "ryzen 5600gt"


@pytest.mark.parametrize("category,key,titles,name", [
    ("gpu", "rtx 5070 ti super", [], "GeForce RTX 5070 Ti Super"),
    ("gpu", "rx 7600 xt", [], "Radeon RX 7600 XT"),
    ("gpu", "rx 9070 gre", [], "Radeon RX 9070 GRE"),
    ("gpu", "arc b570", [], "Arc B570"),
    ("cpu", "ryzen 5600gt", ["AMD Ryzen 5 5600GT Processor"], "Ryzen 5 5600GT"),
    ("cpu", "ryzen 9850x3d", [], "Ryzen 7 9850X3D"),
    ("cpu", "ryzen 8300g", [], "Ryzen 3 8300G"),
    ("cpu", "ultra 270k plus", ["Intel Core Ultra 7 270K Plus"], "Core Ultra 7 270K Plus"),
    ("cpu", "ultra 250k plus", [], "Core Ultra 5 250K Plus"),
    ("cpu", "core 14600kf", [], "Core i5-14600KF"),
    ("cpu", "core 14100", [], "Core i3-14100"),
])
def test_model_name(category, key, titles, name):
    assert r.model_name(category, key, titles) == name


def test_model_name_matches_every_watchlist_row():
    # Generated names round-trip the CSV's own naming for every tracked product
    # (VRAM-suffixed variants excepted -- their VRAM is added separately).
    for wp in load_watchlist():
        key = chip_key(wp["model"], wp["category"])
        name = r.model_name(wp["category"], key, [wp["model"]])
        assert wp["model"].startswith(name), (wp["model"], name)


def test_display_name_adds_vram_for_gpus():
    assert r.display_name("gpu", "rtx 5050", 8, []) == "GeForce RTX 5050 8GB"
    assert r.display_name("gpu", "rtx 5050", None, []) == "GeForce RTX 5050"
    assert r.display_name("cpu", "ryzen 5600gt", None, []) == "Ryzen 5 5600GT"


def test_suggested_rows():
    assert r.suggested_row("gpu", "rtx 5050", 8, [], vram_in_model=False) == \
        'gpu,NVIDIA,GeForce RTX 5050,8GB,current'
    assert r.suggested_row("gpu", "rtx 5060", 8, [], vram_in_model=True) == \
        'gpu,NVIDIA,GeForce RTX 5060 8GB,8GB,current'
    assert r.suggested_row("cpu", "ryzen 5600gt", None, [], vram_in_model=False) == \
        'cpu,AMD,Ryzen 5 5600GT,?c,current-2'
    assert r.suggested_row("gpu", "rtx 5050", None, [], vram_in_model=False).split(",")[3] == "?GB"
