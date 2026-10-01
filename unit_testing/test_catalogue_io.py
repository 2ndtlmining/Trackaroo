"""Catalogue sidecar files for the discovery report (#16)."""
import json
import os
from datetime import date

from scraper import catalogue_io as cio


def _item(title="MSI RTX 5050 8G", price=389.0):
    return cio.catalogue_item(title, "https://x/1", price, "in_stock", "SKU1")


def test_save_writes_into_catalogue_subfolder(tmp_path):
    path = cio.save_catalogue(tmp_path, "scorptec", "gpu", "02_October_2026", [_item()])
    assert path == tmp_path / "catalogue" / "scorptec_gpu_02_October_2026.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["retailer"] == "scorptec" and body["category"] == "gpu"
    assert body["date"] == "02_October_2026"
    assert body["items"][0] == {
        "title": "MSI RTX 5050 8G", "url": "https://x/1", "price_aud": 389.0,
        "stock_status": "in_stock", "sku": "SKU1",
    }
    # Nothing at the top of data/: ingest globs data/*_{date}.json.
    assert [p.name for p in tmp_path.iterdir()] == ["catalogue"]


def test_save_replaces_same_day_file_even_if_smaller(tmp_path):
    cio.save_catalogue(tmp_path, "pccg", "cpu", "02_October_2026", [_item(), _item("B")])
    path = cio.save_catalogue(tmp_path, "pccg", "cpu", "02_October_2026", [_item()])
    assert len(json.loads(path.read_text(encoding="utf-8"))["items"]) == 1


def test_save_never_raises(tmp_path, monkeypatch, caplog):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(cio.os, "replace", boom)
    assert cio.save_catalogue(tmp_path, "umart", "gpu", "02_October_2026", [_item()]) is None
    assert "catalogue" in caplog.text.lower()
    assert not list((tmp_path / "catalogue").glob("*.tmp"))


def test_load_reads_only_that_day_and_reports_bad_files(tmp_path):
    cio.save_catalogue(tmp_path, "scorptec", "gpu", "02_October_2026", [_item()])
    cio.save_catalogue(tmp_path, "scorptec", "gpu", "01_October_2026", [_item()])
    (tmp_path / "catalogue" / "pccg_gpu_02_October_2026.json").write_text("{nope", encoding="utf-8")
    envelopes, bad = cio.load_catalogues(tmp_path, "02_October_2026")
    assert [(e["retailer"], e["category"]) for e in envelopes] == [("scorptec", "gpu")]
    assert bad == ["pccg_gpu_02_October_2026.json"]


def test_load_with_no_folder_is_empty(tmp_path):
    assert cio.load_catalogues(tmp_path, "02_October_2026") == ([], [])


def test_prune_keeps_30_days(tmp_path):
    for d in ("02_October_2026", "02_September_2026", "01_September_2026"):
        cio.save_catalogue(tmp_path, "umart", "cpu", d, [_item()])
    (tmp_path / "catalogue" / "notes.txt").write_text("keep", encoding="utf-8")
    removed = cio.prune_catalogues(tmp_path, keep_days=30, today=date(2026, 10, 2))
    names = sorted(p.name for p in (tmp_path / "catalogue").iterdir())
    assert removed == 1
    assert names == ["notes.txt", "umart_cpu_02_October_2026.json", "umart_cpu_02_September_2026.json"]
