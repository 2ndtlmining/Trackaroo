"""
Tests for watchlist row validation (db/watchlist.py).

Why this exists: before 31-Aug-2026 a one-character typo in `watchlist.csv`
stopped the container from starting. `parse_spec` did a literal
``int(spec.replace("GB", ""))``, so a lowercase ``16gb`` raised ValueError,
which propagated out of `load_watchlist`, exited `seed.py` with status 1, and
`deploy/entrypoint-single.sh` runs `python seed.py` under `set -e`. Every
scraper failed the same way, since they all call `load_watchlist()`.

The rule now: **one bad row costs one product, never the whole run.** Invalid
rows are reported by line number and field and then skipped, so the tracker
keeps running on the remaining ones. `strict=True` is available for tooling
that wants the exception instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.watchlist import (  # noqa: E402
    DEFAULT_WATCHLIST_PATH,
    WatchlistRowError,
    load_all_rows,
    load_watchlist,
    load_watchlist_products,
    parse_spec,
    validate_row,
)

HEADER = "category,brand,model,spec,series,status\n"
GOOD = 'gpu,NVIDIA,GeForce RTX 5070,12GB,rtx50,active\n'
GOOD_CPU = 'cpu,AMD,Ryzen 5 9600X,6c,zen5,active\n'


def _csv(tmp_path, *rows, comment=True):
    text = ("# a comment line\n" if comment else "") + HEADER + "".join(rows)
    p = tmp_path / "watchlist.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


class TestParseSpecIsForgivingAboutFormatting:
    """A human edits this file by hand; case and spacing must not be a trap."""

    @pytest.mark.parametrize("spec", ["16c", "16C", "16 c", " 16c "])
    def test_accepts_cpu_core_spellings(self, spec):
        assert parse_spec(spec, "cpu")["cores"] == 16

    @pytest.mark.parametrize("spec", ["16GB", "16gb", "16 GB", " 16Gb "])
    def test_accepts_gpu_vram_spellings(self, spec):
        assert parse_spec(spec, "gpu")["vram_gb"] == 16

    @pytest.mark.parametrize("spec", ["", "   ", "8c/16t", "sixteen", "GB"])
    def test_rejects_what_it_cannot_understand(self, spec):
        with pytest.raises(WatchlistRowError):
            parse_spec(spec, "gpu")

    def test_the_error_says_what_was_wrong(self):
        with pytest.raises(WatchlistRowError) as exc:
            parse_spec("16gib", "gpu")
        assert "16gib" in str(exc.value)


class TestValidateRow:
    def _row(self, **over):
        row = {
            "category": "gpu",
            "brand": "NVIDIA",
            "model": "GeForce RTX 5070",
            "spec": "12GB",
            "series": "rtx50",
            "status": "active",
        }
        row.update(over)
        return row

    def test_accepts_a_good_row(self):
        assert validate_row(self._row(), line_no=7)["model"] == "GeForce RTX 5070"

    @pytest.mark.parametrize(
        "field,value",
        [
            ("category", "ram"),
            ("brand", "Gigabyte"),
            ("series", "zen5"),  # a CPU series on a GPU row
            ("series", "nope"),
            ("status", "gone"),
            ("model", ""),
            ("spec", "12"),
        ],
    )
    def test_rejects_a_bad_field(self, field, value):
        with pytest.raises(WatchlistRowError):
            validate_row(self._row(**{field: value}), line_no=7)

    def test_the_error_names_the_line_and_the_field(self):
        """A message that does not say which row is barely better than a crash."""
        with pytest.raises(WatchlistRowError) as exc:
            validate_row(self._row(brand="Gigabyte"), line_no=42)
        message = str(exc.value)
        assert "42" in message
        assert "brand" in message

    def test_a_missing_column_is_a_row_error_not_a_keyerror(self):
        row = self._row()
        del row["series"]
        with pytest.raises(WatchlistRowError):
            validate_row(row, line_no=3)


class TestSearchAliasesRetired:
    """#20: matching is chip-key only, so the alias column was dropped."""

    def test_a_row_needs_no_alias_column(self):
        row = {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5070",
               "spec": "12GB", "series": "rtx50", "status": "active"}
        out = validate_row(row, line_no=2)
        assert out["vram_gb"] == 12
        assert "search_terms" not in out

    def test_a_legacy_csv_with_the_alias_column_still_loads(self, tmp_path):
        p = tmp_path / "watchlist.csv"
        p.write_text("category,brand,model,spec,series,status,search_aliases\n"
                     'gpu,NVIDIA,GeForce RTX 5070,12GB,rtx50,active,"rtx 5070"\n', encoding="utf-8")
        assert [w["model"] for w in load_watchlist(str(p))] == ["GeForce RTX 5070"]

    def test_the_real_csv_has_no_alias_column_and_says_how_matching_works(self):
        text = Path(DEFAULT_WATCHLIST_PATH).read_text(encoding="utf-8")
        header = next(line for line in text.splitlines() if line and not line.startswith("#"))
        assert header == "category,brand,model,spec,series,status"
        assert "search_aliases" not in text
        assert "chip key" in text
        assert "NOT overwritten" not in text

    @pytest.mark.parametrize("title,category,model", [
        ("Radeon RX 9070GRE", "gpu", "Radeon RX 9070 GRE"),
        ("RTX5070 Ti", "gpu", "GeForce RTX 5070 Ti"),
        ("Core i5-14400F", "cpu", "Core i5-14400F"),
    ])
    def test_retailer_spellings_resolve_to_the_watchlist_row(self, title, category, model):
        from scraper.chip_key import chip_key
        assert chip_key(title, category) == chip_key(model, category)
        assert any(w["model"] == model for w in load_watchlist())


class TestLoadWatchlistSkipsBadRows:
    def test_a_bad_row_does_not_take_down_the_load(self, tmp_path):
        path = _csv(tmp_path, GOOD, 'gpu,NVIDIA,Broken,16gib,rtx50,active\n', GOOD_CPU)
        products = load_watchlist(path)
        assert [p["model"] for p in products] == ["GeForce RTX 5070", "Ryzen 5 9600X"]

    def test_the_seeder_loader_skips_it_too(self, tmp_path):
        path = _csv(tmp_path, GOOD, 'cpu,AMD,Broken,,zen5,active\n')
        products = load_watchlist_products(path)
        assert [p["model"] for p in products] == ["GeForce RTX 5070"]

    def test_the_skipped_row_is_reported(self, tmp_path, caplog):
        """Silently dropping a product would be its own kind of bug."""
        path = _csv(tmp_path, GOOD, 'gpu,NVIDIA,Broken,16gib,rtx50,active\n')
        with caplog.at_level("ERROR"):
            load_watchlist(path)
        assert any("Broken" in r.message or "16gib" in r.message for r in caplog.records)

    def test_strict_mode_raises_instead(self, tmp_path):
        path = _csv(tmp_path, GOOD, 'gpu,NVIDIA,Broken,16gib,rtx50,active\n')
        with pytest.raises(WatchlistRowError):
            load_watchlist(path, strict=True)

    def test_an_all_bad_file_yields_nothing_rather_than_raising(self, tmp_path):
        path = _csv(tmp_path, 'gpu,NVIDIA,Broken,16gib,rtx50,active\n')
        assert load_watchlist(path) == []


class TestTheRealWatchlistIsClean:
    """Alias-ordering no longer decides matching (#1): scrapers now resolve
    through the chip-key `Matcher`, which matches on an exact key rather than
    a substring race between primary search terms. The alias-ordering trap
    this class used to test for no longer exists; the equivalent guarantee —
    every real watchlist row has a key and no two rows collide on it — is
    `test_chip_key.py::test_every_watchlist_row_has_a_key_and_no_collisions`.
    """

    def test_every_row_validates(self):
        """The shipped file must have no rows that would be skipped."""
        # strict=True raises on the first bad row; the floor catches truncation
        # without pinning a count every add or retire would have to bump (#20).
        assert len(load_watchlist(strict=True)) >= 70


class TestKnownMissingSpecsAreSeparated:
    """Four AMD parts have no amd.com page at all, verified 31-Aug-2026: every
    URL form for Ryzen 5 5500 / 5 5600 / 7 5700X / 9 9900 redirects to the
    homepage. They will never match, and they had been sitting in the unmatched
    report for weeks.

    That is the actual risk: four permanent entries train the reader to skim
    the list, so a genuinely new gap -- a product that *should* have specs --
    hides among them. Separating "known absent upstream" from "unmatched" keeps
    the second list meaningful.
    """

    def test_the_known_list_is_documented_with_reasons(self):
        import sync_specs

        assert sync_specs.SPECS_UNAVAILABLE_UPSTREAM
        for model, reason in sync_specs.SPECS_UNAVAILABLE_UPSTREAM.items():
            assert reason.strip(), f"{model} needs a reason, not a bare entry"

    def test_it_names_the_four_retired_amd_parts(self):
        import sync_specs

        assert set(sync_specs.SPECS_UNAVAILABLE_UPSTREAM) == {
            "Ryzen 5 5500",
            "Ryzen 5 5600",
            "Ryzen 7 5700X",
            "Ryzen 9 9900",
        }

    def test_every_entry_is_a_real_watchlist_product(self):
        """An entry for a product that no longer exists would hide a typo."""
        import sync_specs

        models = {p["model"] for p in load_watchlist(strict=True)}
        for model in sync_specs.SPECS_UNAVAILABLE_UPSTREAM:
            assert model in models, f"{model} is not in the watchlist"

    def test_a_known_absent_product_is_not_reported_as_unmatched(self):
        import sync_specs

        stats = {"unmatched_products": [], "known_missing": []}
        sync_specs.record_unmatched(stats, {"id": 1, "model": "Ryzen 5 5500"})
        sync_specs.record_unmatched(stats, {"id": 2, "model": "GeForce RTX 5070"})

        assert [u["model"] for u in stats["unmatched_products"]] == ["GeForce RTX 5070"]
        assert [u["model"] for u in stats["known_missing"]] == ["Ryzen 5 5500"]


def test_every_launch_msrp_key_names_a_watchlist_model():
    """db/launch_msrp.json is keyed by products.model and edited by hand next
    to watchlist.csv (#20): a typo there would silently never apply. Retired
    rows count: their products stay in the DB with their MSRP."""
    import json

    msrp = json.loads((Path(DEFAULT_WATCHLIST_PATH).parent / "launch_msrp.json").read_text(encoding="utf-8"))
    models = {w["model"] for w in load_all_rows()}
    assert sorted(k for k in msrp if k not in models) == []
