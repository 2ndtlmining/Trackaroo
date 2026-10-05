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
