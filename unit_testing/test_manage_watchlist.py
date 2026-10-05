"""manage_watchlist.py: rollover / retire / check (#19). Runs on tmp copies, never db/trackaroo.db."""
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
import manage_watchlist
import sync_specs
from manage_watchlist import main

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"


@pytest.fixture
def files(tmp_path, monkeypatch):
    csv_p, toml_p = tmp_path / "watchlist.csv", tmp_path / "generations.toml"
    shutil.copyfile(ROOT / "db" / "watchlist.csv", csv_p)
    shutil.copyfile(ROOT / "db" / "generations.toml", toml_p)
    monkeypatch.setattr(manage_watchlist, "CSV_PATH", str(csv_p))
    monkeypatch.setattr(manage_watchlist, "TOML_PATH", str(toml_p))
    return SimpleNamespace(csv=csv_p, toml=toml_p)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    yield conn
    conn.close()


def status_of(csv_path, model):
    for line in csv_path.read_text().splitlines():
        parts = line.split(",")
        if len(parts) == 6 and parts[2] == model:
            return parts[5]
    raise AssertionError(f"{model} not in csv")


ROLLOVER = ["rollover", "amd-cpu", "--new", "zen6", "--label", "Ryzen 10000 (Zen 6)", "--chips", "ryzen:10"]


def test_rollover_dry_run_lists_retags_and_retirements_and_writes_nothing(files, capsys):
    before = (files.csv.read_text(), files.toml.read_text())
    assert main(ROLLOVER + ["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Ryzen 7 9700X: current -> current-1" in out
    assert "RETIRE Ryzen 5 5600" in out
    assert "Dry run: nothing written." in out
    assert (files.csv.read_text(), files.toml.read_text()) == before


def test_rollover_writes_toml_only(files, capsys):
    csv_before = files.csv.read_bytes()
    assert main(ROLLOVER) == 0
    out = capsys.readouterr().out
    assert files.csv.read_bytes() == csv_before
    from db.generations import parse_generations
    gens = parse_generations(files.toml.read_text())
    assert gens.lines["amd-cpu"].series[0].key == "zen6"
    assert gens.series["zen6"].chips == ("ryzen:10",)
    assert "Next: python seed.py --dry-run, then python seed.py --allow-bulk (on the host after deploy)." in out


def test_rollover_duplicate_key_exits_1_and_writes_nothing(files, capsys):
    before = files.toml.read_text()
    assert main(["rollover", "amd-cpu", "--new", "zen5", "--label", "x", "--chips", "ryzen:10"]) == 1
    assert "zen5" in capsys.readouterr().out
    assert files.toml.read_text() == before


def test_retire_model(files, capsys):
    assert status_of(files.csv, "Ryzen 7 5800X3D") == "active"
    assert main(["retire", "Ryzen 7 5800X3D"]) == 0
    assert status_of(files.csv, "Ryzen 7 5800X3D") == "retired"
    assert "RETIRE Ryzen 7 5800X3D" in capsys.readouterr().out


def test_retire_dry_run_writes_nothing(files, capsys):
    before = files.csv.read_text()
    assert main(["retire", "Ryzen 7 5800X3D", "--dry-run"]) == 0
    assert files.csv.read_text() == before
    assert "RETIRE Ryzen 7 5800X3D" in capsys.readouterr().out


def test_retire_series(files):
    zen3 = [l.split(",")[2] for l in files.csv.read_text().splitlines() if l.endswith(",zen3,active")]
    assert zen3
    assert main(["retire", "--series", "zen3"]) == 0
    for m in zen3:
        assert status_of(files.csv, m) == "retired"
    assert status_of(files.csv, "Ryzen 7 9700X") == "active"


def test_retire_unknown_model_exits_1(files, capsys):
    before = files.csv.read_text()
    assert main(["retire", "Ryzen 99 9999X"]) == 1
    assert "model not found in watchlist: Ryzen 99 9999X" in capsys.readouterr().out
    assert files.csv.read_text() == before


def test_retire_stale_reads_pending_and_requested(files, db):
    ids = {}
    for model in ("Ryzen 7 5800X3D", "Ryzen 5 5600X", "Ryzen 7 9700X"):
        ids[model] = db.execute(
            "INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', ?, 1)", (model,)
        ).lastrowid
    for model, decision in (("Ryzen 7 5800X3D", "pending"), ("Ryzen 5 5600X", "requested"), ("Ryzen 7 9700X", "kept")):
        db.execute(
            "INSERT INTO retire_suggestions (product_id, first_flagged, decision) VALUES (?, '2026-09-01', ?)",
            (ids[model], decision),
        )
    db.commit()
    assert main(["retire", "--stale"]) == 0
    assert status_of(files.csv, "Ryzen 7 5800X3D") == "retired"
    assert status_of(files.csv, "Ryzen 5 5600X") == "retired"
    assert status_of(files.csv, "Ryzen 7 9700X") == "active"  # kept: untouched


def test_check_passes_on_the_real_files(files, capsys):
    assert main(["check"]) == 0
    assert capsys.readouterr().out.startswith("OK: ")


def test_check_fails_on_chip_collision(files, capsys):
    with open(files.csv, "a", encoding="utf-8", newline="") as f:
        f.write("cpu,AMD,Ryzen 7 9700X Boxed,8c,zen5,retired\n")
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert "Ryzen 7 9700X" in out and "Ryzen 7 9700X Boxed" in out and "collision" in out


def test_check_cpu_chip_key_collision_with_different_core_counts(files, capsys):
    """The Matcher drops CPU rows sharing a chip key whatever their spec says."""
    with open(files.csv, "a", encoding="utf-8", newline="") as f:
        f.write("cpu,AMD,Ryzen 7 9700X Tray,6c,zen5,active\n")
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert "collision" in out and "Ryzen 7 9700X Tray" in out and "Ryzen 7 9700X" in out


def test_check_collects_all_problems(files, capsys):
    with open(files.csv, "a", encoding="utf-8", newline="") as f:
        f.write("cpu,AMD,Ryzen 7 9700X Boxed,8c,zen5,retired\n")
        f.write("cpu,AMD,Ryzen 5 9600X,six,zen5,active\n")
        f.write("cpu,AMD,Ryzen 5 9600X2,6c,nonesuch,active\n")
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert "collision" in out and "[spec]" in out and "[series]" in out
    assert "3 problem(s)." in out


def test_check_fails_on_orphan_specs_unavailable(files, monkeypatch, capsys):
    monkeypatch.setitem(sync_specs.SPECS_UNAVAILABLE_UPSTREAM, "Ryzen 9 ghost", "gone")
    assert main(["check"]) == 1
    assert "Ryzen 9 ghost" in capsys.readouterr().out


def test_add_appends_after_its_series_and_lists_follow_ups(files, capsys):
    assert main(["add", "Ryzen 7 10700X", "--spec", "8c", "--series", "zen5"]) == 0
    lines = files.csv.read_text().splitlines()
    assert "cpu,AMD,Ryzen 7 10700X,8c,zen5,active" in lines
    zen5 = [i for i, l in enumerate(lines) if l.endswith(",zen5,active") or l.endswith(",zen5,retired")]
    assert lines.index("cpu,AMD,Ryzen 7 10700X,8c,zen5,active") == zen5[-1]  # last zen5 row
    out = capsys.readouterr().out
    assert "launch_msrp.json" in out and "perf_index.json" in out
    assert "sync_specs.py" in out and "SPECS_UNAVAILABLE_UPSTREAM" in out
    assert main(["check"]) == 0


def test_add_infers_brand_and_category_from_the_series(files):
    assert main(["add", "GeForce RTX 5070 SUPER", "--spec", "18GB", "--series", "rtx50"]) == 0
    assert "gpu,NVIDIA,GeForce RTX 5070 SUPER,18GB,rtx50,active" in files.csv.read_text().splitlines()


def test_add_refuses_a_chip_collision(files, capsys):
    before = files.csv.read_bytes()
    assert main(["add", "GeForce RTX 5070", "--spec", "12GB", "--series", "rtx50"]) == 1
    assert "collision" in capsys.readouterr().out
    assert files.csv.read_bytes() == before


def test_add_allows_same_chip_different_vram(files):
    assert main(["add", "GeForce RTX 5070", "--spec", "16GB", "--series", "rtx50"]) == 0
    assert "gpu,NVIDIA,GeForce RTX 5070,16GB,rtx50,active" in files.csv.read_text().splitlines()


def test_add_rejects_bad_spec_and_unknown_series(files, capsys):
    before = files.csv.read_bytes()
    assert main(["add", "Ryzen 7 10700X", "--spec", "eight", "--series", "zen5"]) == 1
    assert "[spec]" in capsys.readouterr().out
    assert main(["add", "Ryzen 7 10700X", "--spec", "8c", "--series", "nonesuch"]) == 1
    assert "nonesuch" in capsys.readouterr().out
    assert files.csv.read_bytes() == before


def test_add_dry_run_writes_nothing(files, capsys):
    before = files.csv.read_bytes()
    assert main(["add", "Ryzen 7 10700X", "--spec", "8c", "--series", "zen5", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "+cpu,AMD,Ryzen 7 10700X,8c,zen5,active" in out and "Dry run: nothing written." in out
    assert files.csv.read_bytes() == before


def _product(db, category, brand, model):
    return db.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES (?, ?, ?, 1)", (category, brand, model)
    ).lastrowid


@pytest.fixture
def listing(db):
    plain = _product(db, "gpu", "NVIDIA", "GeForce RTX 3060")
    ti = _product(db, "gpu", "NVIDIA", "GeForce RTX 3060 Ti")
    lid = db.execute(
        "INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url) "
        "VALUES (?, 'pccg', 'Gigabyte 3060 Ti', 'https://example.test/x')",
        (plain,),
    ).lastrowid
    for day in ("2026-10-01", "2026-10-02"):
        db.execute(
            "INSERT INTO price_snapshots (retailer_listing_id, price_aud, snapshot_date) "
            "VALUES (?, 499.0, ?)", (lid, day),
        )
    db.commit()
    return SimpleNamespace(id=lid, plain=plain, ti=ti)


def test_reassign_dry_run_prints_listing_and_snapshot_count(db, listing, capsys):
    assert main(["reassign", str(listing.id), "GeForce RTX 3060 Ti", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert (f"listing {listing.id} pccg 'Gigabyte 3060 Ti' : GeForce RTX 3060 -> GeForce RTX 3060 Ti "
            "(2 snapshots stay attached)") in out
    assert db.execute("SELECT product_id FROM retailer_listings WHERE id=?", (listing.id,)).fetchone()[0] == listing.plain


def test_reassign_moves_listing_and_leaves_snapshots_byte_identical(db, listing, monkeypatch):
    monkeypatch.setattr(manage_watchlist, "backup_database", lambda **kw: "backup")
    before = db.execute("SELECT * FROM price_snapshots ORDER BY id").fetchall()
    assert main(["reassign", str(listing.id), "GeForce RTX 3060 Ti"]) == 0
    assert db.execute("SELECT product_id FROM retailer_listings WHERE id=?", (listing.id,)).fetchone()[0] == listing.ti
    assert db.execute("SELECT * FROM price_snapshots ORDER BY id").fetchall() == before


def test_reassign_takes_a_backup_first(db, listing, monkeypatch):
    seen = []

    def fake_backup(**kw):
        seen.append(db.execute("SELECT product_id FROM retailer_listings WHERE id=?", (listing.id,)).fetchone()[0])
        return "backup"

    monkeypatch.setattr(manage_watchlist, "backup_database", fake_backup)
    assert main(["reassign", str(listing.id), "GeForce RTX 3060 Ti"]) == 0
    assert seen == [listing.plain]  # backup ran while the listing was still on the old product


def test_reassign_dry_run_takes_no_backup(db, listing, monkeypatch):
    monkeypatch.setattr(manage_watchlist, "backup_database", lambda **kw: pytest.fail("backup on dry run"))
    assert main(["reassign", str(listing.id), "GeForce RTX 3060 Ti", "--dry-run"]) == 0


def test_reassign_unknown_listing_or_ambiguous_model_exits_1(db, listing, capsys):
    assert main(["reassign", "9999", "GeForce RTX 3060 Ti"]) == 1
    assert "listing 9999" in capsys.readouterr().out
    assert main(["reassign", str(listing.id), "GeForce RTX 9999"]) == 1
    assert "GeForce RTX 9999" in capsys.readouterr().out
    _product(db, "gpu", "Other", "GeForce RTX 3060 Ti")
    db.commit()
    assert main(["reassign", str(listing.id), "GeForce RTX 3060 Ti"]) == 1
    out = capsys.readouterr().out
    assert "NVIDIA" in out and "Other" in out
    assert db.execute("SELECT product_id FROM retailer_listings WHERE id=?", (listing.id,)).fetchone()[0] == listing.plain
