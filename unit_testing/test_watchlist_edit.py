"""Pure text edits for the watchlist CSV and generations.toml (#19)."""
import pytest

from db.generations import parse_generations
from watchlist_edit import append_row, insert_series, set_status, unified

TOML = '''# header comment
[[line]]
id = "amd-cpu"
series = [
  { key = "zen5", label = "Ryzen 9000 (Zen 5)", chips = ["ryzen:9"] },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)", chips = ["ryzen:7"] },
]

[[line]]
id = "intel-cpu"
series = [
  { key = "core-14", label = "Core 14th Gen", chips = ["core:14"] },
]
'''

CSV = (
    "# comment one\n"
    "# comment two\n"
    "\n"
    "category,brand,model,spec,series,status\n"
    "cpu,AMD,Ryzen 9 9950X,16c,zen5,active\n"
    "cpu,AMD,Ryzen 7 7700X,8c,zen4,active\n"
    "cpu,AMD,Ryzen 5 7600X,6c,zen4,retired\n"
    "cpu,Intel,Core i5 14400F,10c,core-14,active\n"
    "gpu,NVIDIA,RTX 5070,12GB,rtx50,active\n"
)


def test_insert_series_puts_new_first_in_that_line_only():
    new = insert_series(TOML, "amd-cpu", "zen6", "Ryzen 10000 (Zen 6)", ["ryzen:10"])
    assert '  { key = "zen6", label = "Ryzen 10000 (Zen 6)", chips = ["ryzen:10"] },\n' in new
    gens = parse_generations(new)
    assert [s.key for s in gens.lines["amd-cpu"].series] == ["zen6", "zen5", "zen4"]
    assert gens.series["zen6"].position == 0
    assert [s.key for s in gens.lines["intel-cpu"].series] == ["core-14"]
    # only one line was added
    assert len(new.splitlines()) == len(TOML.splitlines()) + 1


def test_insert_series_duplicate_key_raises():
    with pytest.raises(ValueError, match="zen5"):
        insert_series(TOML, "amd-cpu", "zen5", "x", [])


def test_insert_series_unknown_line_raises():
    with pytest.raises(ValueError, match="nvidia-gpu"):
        insert_series(TOML, "nvidia-gpu", "rtx60", "x", [])


def test_set_status_flips_exactly_the_named_rows_case_insensitive():
    new, changed = set_status(CSV, {"ryzen 7 7700x", "Core i5 14400F"}, "retired")
    assert sorted(changed) == ["Core i5 14400F", "Ryzen 7 7700X"]
    old_lines, new_lines = CSV.splitlines(True), new.splitlines(True)
    diff = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert diff == [5, 7]
    assert new_lines[5] == "cpu,AMD,Ryzen 7 7700X,8c,zen4,retired\n"
    assert new_lines[7] == "cpu,Intel,Core i5 14400F,10c,core-14,retired\n"
    assert new_lines[:3] == old_lines[:3]  # comments + blank byte-identical


def test_set_status_noop_for_already_retired():
    new, changed = set_status(CSV, {"Ryzen 5 7600X"}, "retired")
    assert changed == []
    assert new == CSV


def test_set_status_exact_match_only():
    new, changed = set_status(CSV, {"Ryzen 7 7700"}, "retired")
    assert changed == [] and new == CSV


def test_crlf_preserved():
    old = CSV.replace("\n", "\r\n")
    new, changed = set_status(old, {"Ryzen 9 9950X"}, "retired")
    assert changed == ["Ryzen 9 9950X"]
    assert "\n" not in new.replace("\r\n", "")
    o, n = old.splitlines(True), new.splitlines(True)
    assert len(o) == len(n)
    assert [i for i in range(len(o)) if o[i] != n[i]] == [4]
    assert n[4] == "cpu,AMD,Ryzen 9 9950X,16c,zen5,retired\r\n"


def test_insert_series_crlf_preserved():
    old = TOML.replace("\n", "\r\n")
    new = insert_series(old, "amd-cpu", "zen6", "Z", ["ryzen:10"])
    assert "\n" not in new.replace("\r\n", "")


def test_append_row_after_the_series():
    new = append_row(CSV, ["cpu", "AMD", "Ryzen 5 7600", "6c", "zen4", "active"], "zen4", "amd-cpu")
    lines = new.splitlines()
    assert lines.index("cpu,AMD,Ryzen 5 7600,6c,zen4,active") == lines.index("cpu,AMD,Ryzen 5 7600X,6c,zen4,retired") + 1


def test_append_row_new_series_goes_after_the_last_row_of_the_line():
    new = append_row(CSV, ["cpu", "AMD", "Ryzen 9 10950X", "16c", "zen6", "active"], "zen6", "amd-cpu")
    lines = new.splitlines()
    assert lines[lines.index("cpu,AMD,Ryzen 5 7600X,6c,zen4,retired") + 1] == "cpu,AMD,Ryzen 9 10950X,16c,zen6,active"


def test_append_row_unknown_line_goes_at_the_end_and_keeps_newlines():
    new = append_row(CSV, ["gpu", "AMD", "RX 9070", "16GB", "rdna4", "active"], None, "amd-gpu")
    assert new == CSV + "gpu,AMD,RX 9070,16GB,rdna4,active\n"
    crlf = CSV.replace("\n", "\r\n")
    assert append_row(crlf, ["gpu", "AMD", "RX 9070", "16GB", "rdna4", "active"], None, "amd-gpu").endswith(
        "RTX 5070,12GB,rtx50,active\r\ngpu,AMD,RX 9070,16GB,rdna4,active\r\n"
    )


def test_unified_names_the_file():
    d = unified("a\n", "b\n", "watchlist.csv")
    assert d.startswith("--- a/watchlist.csv\n+++ b/watchlist.csv\n")
    assert "-a\n" in d and "+b\n" in d
    assert unified("a\n", "a\n", "x") == ""
