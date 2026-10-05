"""db/generations.py: parsing, validation and tier derivation (#17)."""
import pytest

from db.generations import (
    TIERS, GenerationsError, default_generations, line_id, load_generations, parse_generations,
)

MINI = """
[[line]]
id = "amd-cpu"
series = [
  { key = "zen6", label = "Ryzen 10000 (Zen 6)", chips = ["ryzen:10"] },
  { key = "zen5", label = "Ryzen 9000 (Zen 5)", chips = ["ryzen:9"] },
  { key = "zen4", label = "Ryzen 7000 (Zen 4)", chips = ["ryzen:7", "ryzen:8"] },
  { key = "zen3", label = "Ryzen 5000 (Zen 3)", chips = ["ryzen:5"] },
]

[[line]]
id = "intel-gpu"
keep_all = true
series = [
  { key = "arc-c", label = "Arc C", chips = ["arc:c"] },
  { key = "arc-b", label = "Arc B", chips = ["arc:b"] },
  { key = "arc-a", label = "Arc A", chips = ["arc:a"] },
  { key = "arc-x", label = "Arc X", chips = [] },
]
"""


def test_position_gives_tier():
    g = parse_generations(MINI)
    assert [g.tier(k) for k in ("zen6", "zen5", "zen4")] == list(TIERS)


def test_fourth_series_is_out_of_scope():
    g = parse_generations(MINI)
    assert g.tier("zen3") is None
    assert g.in_scope("zen3") is False


def test_keep_all_keeps_old_series_in_scope_at_current_2():
    g = parse_generations(MINI)
    assert g.in_scope("arc-x") is True
    assert g.tier("arc-x") == "current-2"


def test_chip_lookup():
    g = parse_generations(MINI)
    assert g.chip_series("ryzen", "8").key == "zen4"
    assert g.chip_series("ryzen", "3") is None
    assert sorted(g.chip_gens("ryzen")) == ["10", "5", "7", "8", "9"]


def test_line_id():
    assert line_id("AMD", "cpu") == "amd-cpu"
    assert line_id(" NVIDIA ", "GPU") == "nvidia-gpu"


@pytest.mark.parametrize("text, needle", [
    ("not = [valid", "not valid TOML"),
    ("", "no [[line]]"),
    ('[[line]]\nid = "amd-gpu-x"\nseries = [{ key = "a", label = "A" }]', "unknown line"),
    ('[[line]]\nid = "amd-cpu"\nseries = []', "has no series"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "Zen 5", label = "A" }]', "key"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "" }]', "label"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "A" }, { key = "a", label = "B" }]', "duplicate series key"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "A" }]\n[[line]]\nid = "amd-cpu"\nseries = [{ key = "b", label = "B" }]', "duplicate line"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "A", chips = ["ryzen9"] }]', "chip"),
    ('[[line]]\nid = "amd-cpu"\nseries = [{ key = "a", label = "A", chips = ["ryzen:9"] }, { key = "b", label = "B", chips = ["ryzen:9"] }]', "ryzen:9"),
    ('[[line]]\nid = "amd-cpu"\nkeep_all = "yes"\nseries = [{ key = "a", label = "A" }]', "keep_all"),
])
def test_invalid_config_is_rejected_with_a_named_reason(text, needle):
    with pytest.raises(GenerationsError, match=needle.replace("[", r"\[")):
        parse_generations(text)


def test_missing_file(tmp_path):
    with pytest.raises(GenerationsError, match="not found"):
        load_generations(tmp_path / "nope.toml")


def test_real_file_loads_and_matches_todays_labels():
    g = default_generations()
    assert set(g.lines) == {"amd-cpu", "intel-cpu", "nvidia-gpu", "amd-gpu", "intel-gpu"}
    assert g.series["rtx50"].label == "RTX 50 (Blackwell)"
    assert g.series["zen4"].chips == ("ryzen:7", "ryzen:8")
    assert g.lines["intel-gpu"].keep_all is True
    for line in g.lines.values():
        assert len(line.series) >= 2
