# unit_testing/test_catalogue_wiring.py
"""Each scraper writes its full category list to data/catalogue (#16)."""
import json
from unittest import mock

import run_daily
from scraper import pccg, scorptec, umart

SCRAPED = [
    {"name": "Gigabyte RTX 5050 Windforce 8G", "price_aud": 389.0, "stock_status": "in_stock",
     "url": "https://s/1", "retailer_sku": "A1"},
    {"name": "Thermal paste", "price_aud": 9.0, "stock_status": "in_stock",
     "url": "https://s/2", "retailer_sku": None},
]


def test_scorptec_catalogue_items_shape():
    items = scorptec.catalogue_items(SCRAPED)
    assert items[0] == {"title": "Gigabyte RTX 5050 Windforce 8G", "url": "https://s/1",
                        "price_aud": 389.0, "stock_status": "in_stock", "sku": "A1"}
    assert len(items) == 2


def test_umart_catalogue_items_shape():
    assert umart.catalogue_items(SCRAPED)[1]["sku"] is None


def test_scorptec_main_saves_both_categories(tmp_path, monkeypatch):
    monkeypatch.setattr(scorptec, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scorptec, "load_watchlist", lambda: [])
    monkeypatch.setattr(scorptec, "save_category_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(scorptec, "analyze_unmatched", lambda *a, **k: None)
    monkeypatch.setattr(
        scorptec, "scrape_scorptec",
        lambda wl, only_category, report, retired=(): ([], set(), {f"{only_category}_x": SCRAPED}),
    )
    scorptec.main()
    names = sorted(p.name for p in (tmp_path / "catalogue").iterdir())
    assert [n.split("_")[:2] for n in names] == [["scorptec", "cpu"], ["scorptec", "gpu"]]


def test_umart_main_saves_both_categories(tmp_path, monkeypatch):
    monkeypatch.setattr(umart, "DATA_DIR", tmp_path)
    monkeypatch.setattr(umart, "load_watchlist", lambda: [])
    monkeypatch.setattr(umart, "save_category_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(
        umart, "scrape_umart",
        lambda wl, only_category, report, retired=(): ([], set(), {only_category: SCRAPED}),
    )
    umart.main()
    assert len(list((tmp_path / "catalogue").glob("umart_*.json"))) == 2


def test_pccg_scrape_category_saves_catalogue_without_extra_query(tmp_path, monkeypatch):
    hits = [{"name": "ASUS RTX 5050 8GB", "price": "$399.00", "url": "https://p/1", "stock_status": "in_stock"}]
    fetch = mock.Mock(return_value=hits)
    monkeypatch.setattr(pccg, "algolia_fetch_catalogue", fetch)
    pccg.scrape_category("gpu", [], catalogue_dir=tmp_path, file_date="02_October_2026")
    assert fetch.call_count == 1
    body = json.loads((tmp_path / "catalogue" / "pccg_gpu_02_October_2026.json").read_text(encoding="utf-8"))
    assert body["items"][0]["title"] == "ASUS RTX 5050 8GB"
    assert body["items"][0]["price_aud"] == 399.0


def test_pccg_scrape_category_without_dir_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(pccg, "algolia_fetch_catalogue", lambda *a, **k: [
        {"name": "x", "price": "$1", "url": "u", "stock_status": "in_stock"}])
    monkeypatch.chdir(tmp_path)
    pccg.scrape_category("gpu", [])
    assert not (tmp_path / "catalogue").exists()


def test_pccg_malformed_price_never_breaks_scrape(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(pccg, "algolia_fetch_catalogue", lambda *a, **k: [
        {"name": "x", "price": "$,", "url": "u", "stock_status": "in_stock"}])
    with caplog.at_level("WARNING"):
        out = pccg.scrape_category("gpu", [], catalogue_dir=tmp_path, file_date="02_October_2026")
    assert out[2] is False
    assert "Could not save pccg" in caplog.text


def test_pccg_breaker_path_writes_no_catalogue(tmp_path, monkeypatch):
    monkeypatch.setattr(pccg, "algolia_fetch_catalogue", lambda *a, **k: [])
    monkeypatch.setattr(pccg, "_write_cooldown", lambda *a, **k: None)
    out = pccg.scrape_category("gpu", [], catalogue_dir=tmp_path, file_date="02_October_2026")
    assert out == ([], set(), True)
    assert not (tmp_path / "catalogue").exists()


def test_ingest_today_ignores_catalogue_folder(tmp_path, monkeypatch):
    from scraper.catalogue_io import save_catalogue
    save_catalogue(tmp_path, "scorptec", "gpu", "02_October_2026", [])
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    assert run_daily.ingest_today(None, filename="02_October_2026") == {}


def test_dockerignore_excludes_catalogue():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / ".dockerignore").read_text(encoding="utf-8")
    assert "data/catalogue/" in text
