"""db/watchlist.py derives tier and tracked from series + status (#17, #18)."""
import pytest

from db.generations import GenerationsError
from db.watchlist import (
    WatchlistRowError, load_all_rows, load_retired, load_watchlist, load_watchlist_products,
)

TOML = """
[[line]]
id = "amd-cpu"
series = [
  { key = "zen5", label = "Ryzen 9000 (Zen 5)" },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)" },
  { key = "zen3", label = "Ryzen 5000 (Zen 3)" },
  { key = "zen2", label = "Ryzen 3000 (Zen 2)" },
]
[[line]]
id = "nvidia-gpu"
series = [{ key = "rtx50", label = "RTX 50" }]
"""

CSV = """# comment
category,brand,model,spec,series,status
cpu,AMD,Ryzen 7 9700X,8c,zen5,active
cpu,AMD,Ryzen 5 8600G,6c,zen4,active
cpu,AMD,Ryzen 7 5800X3D,8c,zen3,retired
cpu,AMD,Ryzen 5 3600,6c,zen2,active
gpu,NVIDIA,GeForce RTX 5070,12GB,rtx50,active
"""


@pytest.fixture
def files(tmp_path):
    toml = tmp_path / "generations.toml"
    toml.write_text(TOML, encoding="utf-8")
    csv_path = tmp_path / "watchlist.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    return str(csv_path), str(toml)


def _by_model(rows):
    return {r["model"]: r for r in rows}


def test_tier_comes_from_series_position(files):
    rows = _by_model(load_all_rows(files[0], generations_path=files[1]))
    assert rows["Ryzen 7 9700X"]["gen_tier"] == "current"
    assert rows["Ryzen 5 8600G"]["gen_tier"] == "current-1"


def test_retired_status_untracks(files):
    rows = _by_model(load_all_rows(files[0], generations_path=files[1]))
    assert rows["Ryzen 7 5800X3D"]["tracked"] == 0
    assert rows["Ryzen 7 5800X3D"]["gen_tier"] == "current-2"


def test_series_off_the_end_untracks_with_no_tier(files):
    rows = _by_model(load_all_rows(files[0], generations_path=files[1]))
    assert rows["Ryzen 5 3600"]["tracked"] == 0
    assert rows["Ryzen 5 3600"]["gen_tier"] is None


def test_load_watchlist_returns_tracked_rows_only(files):
    models = [r["model"] for r in load_watchlist(files[0], generations_path=files[1])]
    assert models == ["Ryzen 7 9700X", "Ryzen 5 8600G", "GeForce RTX 5070"]


def test_load_retired_returns_the_sinks(files):
    models = [r["model"] for r in load_retired(files[0], generations_path=files[1])]
    assert models == ["Ryzen 7 5800X3D", "Ryzen 5 3600"]


def test_products_shape_includes_series_and_tracked(files):
    p = _by_model(load_watchlist_products(files[0], generations_path=files[1]))
    assert p["Ryzen 7 5800X3D"] == {
        "category": "cpu", "brand": "AMD", "model": "Ryzen 7 5800X3D", "vram_gb": None,
        "cores": 8, "generation_tier": "current-2", "tracked": 0, "series": "zen3",
    }


@pytest.mark.parametrize("line, field", [
    ("cpu,AMD,Ryzen 9 9950X,16c,zen9,active", "series"),
    ("cpu,AMD,Ryzen 9 9950X,16c,rtx50,active", "series"),
    ("cpu,AMD,Ryzen 9 9950X,16c,zen5,gone", "status"),
])
def test_bad_series_or_status_is_a_row_error(tmp_path, files, line, field):
    bad = tmp_path / "bad.csv"
    bad.write_text("category,brand,model,spec,series,status\n" + line + "\n", encoding="utf-8")
    with pytest.raises(WatchlistRowError) as exc:
        load_all_rows(str(bad), strict=True, generations_path=files[1])
    assert exc.value.field == field
    assert load_all_rows(str(bad), generations_path=files[1]) == []  # non-strict: skipped


def test_broken_generations_file_raises(tmp_path, files):
    broken = tmp_path / "broken.toml"
    broken.write_text("[[line]]\nid = 'nope'\n", encoding="utf-8")
    with pytest.raises(GenerationsError):
        load_watchlist(files[0], generations_path=str(broken))
