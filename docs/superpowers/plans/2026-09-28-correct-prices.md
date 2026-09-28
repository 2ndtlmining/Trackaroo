# Correct Prices Implementation Plan (Phase 1 of the 28-Sep roadmap)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every price Trackaroo shows belongs to the part it is labelled as, comes from a listing that is still on sale, and is only called a "deal" when it is one.

**Architecture:** One shared matcher, `scraper/chip_key.py`, turns any title into a canonical chip key such as `rtx 5060 ti` or `ryzen 5500gt`, plus an optional VRAM figure. A listing belongs to a watchlist row only when the keys are **equal**, and the VRAM also has to agree when several rows share a key. All three scrapers use it. A backup-first `repair_listings.py` applies the same matcher to the existing listings, so history already filed under the wrong product moves too. On the web side:
- A listing that has stopped being seen can no longer set a headline price.
- `/deals` gets thresholds, an "earned low" rule, a single list per product and honest labels.

**Tech Stack:** Python 3.12 + pytest (pipeline), SvelteKit 2 / Svelte 5 + vitest + Playwright (web), SQLite.

**Spec:** GitHub issues #1, #2, #4 and #6, plus the 28-Sep verification findings in `docs/superpowers/plans/2026-09-28-roadmap.md`. Read the issue bodies with `gh issue view N`.

## Global Constraints

- The owner decided on 28-Sep: **GPU memory variants become separate products** (#2, option 1).
- The owner decided on 28-Sep: **deal floor is 2% AND $10** (#6).
- **Never delete `price_snapshots` rows.** They are correct prices for the real part. Only `retailer_listings.product_id` / `status` may change.
- Every DB-mutating script defaults to **dry run**. `--apply` takes a backup through `backup_db.backup_database()` first.
- The regression gate must be green before every commit:
  - from the repo root: `python -m pytest -q`
  - from `web/`: `npm run check`, `npm test`, `npm run test:e2e`
- Windows console: no unicode arrows in Python log output (use `->`).
- No redeploy in this plan. The owner redeploys at the end of all phases.

## Review Focus

1. **Joined spellings and punctuation**, for example `rtx5070ti`, `RX 9070GRE`, `i5-14400F` and `Ryzen 7 5800X3D,`. These must resolve exactly like the spaced forms. Task 1 pins them in the corpus.
2. **A title with no VRAM** for a line that has two memory sizes (5060 Ti, 9060 XT, 3050) must be *unmatched*, never guessed. Pinned in Task 1.
3. **Re-running `repair_listings.py --apply` twice** must change nothing the second time (idempotent). Pinned in Task 4.
4. **A listing marked `stale` whose last snapshot said "in stock"** must never be the headline or the compare "best price". Pinned in Task 5.
5. **A product that is both below its average and at a new low** must appear once on `/deals`, not twice, and the chip counts must equal the rows shown. Pinned in Task 6.

---

## File Structure

| File | Responsibility |
|---|---|
| `scraper/chip_key.py` (new) | `normalise`, `chip_key`, `parse_vram`, `is_excluded`, `Matcher`: the one rule for "is this listing that product" |
| `unit_testing/fixtures/titles.csv` (new) | Real and made-up titles with the expected model (or blank = unmatched) |
| `unit_testing/test_chip_key.py` (new) | Corpus test and the unit rules |
| `scraper/scorptec.py`, `scraper/umart.py`, `scraper/pccg.py` | Use `Matcher` instead of substring matching |
| `db/watchlist.csv` | 5 new rows (4 GPU variants and 245K) |
| `seed.py` | Also sync `vram_gb` / `cores` for existing products |
| `repair_listings.py` (new) | Re-run the matcher over every listing and re-point or park the mis-filed ones |
| `unit_testing/test_repair_listings.py` (new) | Repair behaviour |
| `deploy/bootstrap-data.sh` | Run the repair after a fresh hydrate |
| `web/src/lib/listingsPanel.ts`, `productHeadline.ts`, `offers.ts`, `server/repos.ts`, `constants.ts` | Stale listings are not buyable |
| `web/src/lib/deals.ts`, `routes/deals/*`, `components/OfferRow.svelte`, `formats.ts` | Deal thresholds, earned low, dedupe, honest labels |

---

### Task 1: Canonical chip key module and title corpus

**Files:**
- Create: `scraper/chip_key.py`
- Create: `unit_testing/fixtures/titles.csv`
- Create: `unit_testing/test_chip_key.py`

**Interfaces:**
- Produces:
  - `normalise(text: str) -> str`
  - `chip_key(text: str, category: str) -> Optional[str]`
  - `parse_vram(text: str) -> Optional[int]`
  - `is_excluded(text: str) -> bool`
  - `class Matcher(watchlist: Sequence[WatchlistProduct])` with `.resolve(title: str, category: str, extra_text: str = "") -> Optional[int]`, which returns an index into the watchlist it was built from
  - `Matcher.collisions() -> List[str]`: human-readable problems (rows with no key, or rows sharing a key with no distinct VRAM)

- [ ] **Step 1: Write the corpus fixture**

Create `unit_testing/fixtures/titles.csv`. Column `expected` is a watchlist model or empty (= must be unmatched). The watchlist rows added in Task 3 are used here already; those rows are `GeForce RTX 5060 Ti 8GB`, `Radeon RX 9060 XT 8GB`, `GeForce RTX 3050 6GB`, `Radeon RX 9070 GRE` and `Core Ultra 5 245K`.

```csv
category,title,expected
cpu,amd ryzen 5 5500 desktop processor,Ryzen 5 5500
cpu,amd ryzen 5 5500gt desktop processor,
cpu,AMD Ryzen 5 5500 with Wraith Stealth,Ryzen 5 5500
cpu,AMD Ryzen 5 5600GT 6-Core,
cpu,AMD Ryzen 5 5600 6-Core Processor,Ryzen 5 5600
cpu,AMD Ryzen 7 5800XT Processor,
cpu,AMD Ryzen 7 5800X Processor,Ryzen 7 5800X
cpu,AMD Ryzen 7 5800X3D Processor,Ryzen 7 5800X3D
cpu,AMD Ryzen 9 5900XT 16-Core,
cpu,AMD Ryzen 7 7700X3D Processor,
cpu,AMD Ryzen 7 7700X Processor,Ryzen 7 7700X
cpu,AMD Ryzen 9 9950X3D2 Processor,
cpu,AMD Ryzen 9 9950X3D Processor,Ryzen 9 9950X3D
cpu,AMD R7 9800X3D,Ryzen 7 9800X3D
cpu,AMD Ryzen 5 8600G with Radeon Graphics,Ryzen 5 8600G
cpu,AMD Ryzen 5 5600 Gaming Processor,Ryzen 5 5600
cpu,Intel Core i5-14400F Processor,Core i5-14400F
cpu,Intel Core i5 14400 Processor,Core i5-14400
cpu,Intel Core i9-14900KS,Core i9-14900KS
cpu,Intel Core i7-14700K,Core i7-14700K
cpu,Intel Core i7-14700KF,Core i7-14700KF
cpu,Intel Core Ultra 5 245K Processor,Core Ultra 5 245K
cpu,Intel Core Ultra 5 245 Processor,Core Ultra 5 245
cpu,Intel Core Ultra 5 245KF,Core Ultra 5 245KF
cpu,Intel Core Ultra 7 270K Plus,
cpu,Intel Core Ultra 7 Processor 265K,Core Ultra 7 265K
cpu,Gigabyte Z890 Ultra 5 Power Bundle,
gpu,palit geforce rtx 5060 ti dual 8g,GeForce RTX 5060 Ti 8GB
gpu,asus dual geforce rtx 5060 ti 16gb gddr7 oc edition,GeForce RTX 5060 Ti
gpu,msi geforce rtx 5060 ti 16g shadow 2x oc plus,GeForce RTX 5060 Ti
gpu,Gigabyte GeForce RTX 5060 Ti Eagle OC,
gpu,MSI GeForce RTX5060Ti Ventus 2X 8GB,GeForce RTX 5060 Ti 8GB
gpu,Gigabyte GeForce RTX 5060 Windforce OC 8GB,GeForce RTX 5060
gpu,ASUS GeForce RTX 5070 Ti SUPER 24GB,
gpu,ASUS GeForce RTX 4070 Ti Super 16GB,GeForce RTX 4070 Ti Super
gpu,ASUS GeForce RTX 4070 Ti 12GB,GeForce RTX 4070 Ti
gpu,ASUS GeForce RTX 4070 Super 12GB,GeForce RTX 4070 Super
gpu,gigabyte aorus rtx 5090 ai box. 32gb,
gpu,asus rog astral geforce rtx 5090 oc edition. 32gb,GeForce RTX 5090
gpu,MSI GeForce RTX 3050 Ventus 2X 6G OC,GeForce RTX 3050 6GB
gpu,MSI GeForce RTX 3050 Ventus 2X 8G OC,GeForce RTX 3050
gpu,MSI GeForce RTX 3060 Ventus 2X 8G,
gpu,asus prime radeon rx 9070 xt oc edition. 16gb,Radeon RX 9070 XT
gpu,asus prime radeon rx 9070 evo oc edition. 16gb,Radeon RX 9070
gpu,Sapphire Pulse Radeon RX 9070GRE 12GB,Radeon RX 9070 GRE
gpu,PowerColor Reaper Radeon RX 9060 XT 8GB,Radeon RX 9060 XT 8GB
gpu,PowerColor Reaper Radeon RX 9060 XT 16GB,Radeon RX 9060 XT
gpu,Sapphire Nitro+ Radeon RX 7900 XTX 24GB,Radeon RX 7900 XTX
gpu,Sapphire Pulse Radeon RX 7900 GRE 16GB,Radeon RX 7900 GRE
gpu,Intel Arc B580 Limited Edition 12GB,Arc B580
gpu,ASRock Intel Arc B570 Challenger 10GB,Arc B570
```

(The `. 32gb` form stands in for Scorptec's `, 32gb`, so that the CSV needs no quoting. Both commas and dots normalise to a space.)

- [ ] **Step 2: Write the failing tests**

Create `unit_testing/test_chip_key.py`:

```python
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
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest unit_testing/test_chip_key.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'scraper.chip_key'`.

- [ ] **Step 4: Implement `scraper/chip_key.py`**

```python
"""Canonical chip keys: the one rule for "is this listing that product".

Until 28-Sep-2026 each scraper decided with a substring test on the first
search alias, so any suffix the watchlist had no row for was absorbed by its
sibling: a Ryzen 5 5500GT filed under the 5500, nine RX 9070 GRE cards under
the RX 9070, 8GB RTX 5060 Ti cards under the 16GB product (#1, #2). Here a
title is reduced to a key such as ``rtx 5060 ti`` or ``ryzen 5500gt`` and a
listing matches only a row whose key is EQUAL. An unknown suffix therefore
produces an unknown key and the listing goes unmatched -- missed, which the
discovery report can surface, instead of mis-filed, which nothing surfaces.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from db.watchlist import WatchlistProduct

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Applied to normalise()d text. Each yields groups that build the key.
_GPU_PATTERNS = (
    ("rtx", re.compile(r"\brtx ?(\d{4})(?!\d)(?: ?(ti)(?![a-z]))?(?: ?(super)(?![a-z]))?")),
    ("rx", re.compile(r"\b(?:rx|radeon) ?(\d{4})(?!\d)(?: ?(xtx|xt|gre)(?![a-z]))?")),
    ("arc", re.compile(r"\barc ?([ab]\d{3})(?!\d)")),
)
_CPU_PATTERNS = (
    ("ryzen", re.compile(
        r"\b(?:ryzen ?[3579]|r[3579])(?: pro)? ?(\d{4,5})"
        r"(?: ?(x3d\d?|xt|x|gt|ge|g|f)(?![a-z0-9]))?(?![0-9])")),
    ("ultra", re.compile(
        r"\bultra ?[3579](?: processor)? ?(\d{3})(?!\d)(ks|kf|k|f|t)?(?![a-z])(?: ?(plus)(?![a-z]))?")),
    ("core", re.compile(r"\bi[3579] ?(?:processor )?(\d{4,5})(?!\d)(ks|kf|k|f|t)?(?![a-z])")),
)
_VRAM = re.compile(r"\b(\d{1,2}) ?gb?(?![a-z0-9])")
# Not a card or not a single part: an eGPU enclosure priced as a whole box,
# laptops, docks and CPU+board bundles.
_EXCLUDE = re.compile(r"\b(?:ai box|egpu|laptop|notebook|dock|bundle|combo)\b")


def normalise(text: str) -> str:
    """Lowercase; every run of punctuation/whitespace becomes one space."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def chip_key(text: str, category: str) -> Optional[str]:
    """The canonical chip key in ``text``, or None if no known chip is named."""
    norm = normalise(text)
    patterns = _GPU_PATTERNS if category == "gpu" else _CPU_PATTERNS
    for family, pattern in patterns:
        m = pattern.search(norm)
        if not m:
            continue
        if family == "rtx":
            return " ".join(p for p in ("rtx", m.group(1), m.group(2), m.group(3)) if p)
        if family == "rx":
            return " ".join(p for p in ("rx", m.group(1), m.group(2)) if p)
        if family == "arc":
            return f"arc {m.group(1)}"
        if family == "ryzen":
            return f"ryzen {m.group(1)}{m.group(2) or ''}"
        if family == "ultra":
            return f"ultra {m.group(1)}{m.group(2) or ''}" + (" plus" if m.group(3) else "")
        if family == "core":
            return f"core {m.group(1)}{m.group(2) or ''}"
    return None


def parse_vram(text: str) -> Optional[int]:
    """First memory size in ``text`` ('8g', '16GB', '32 gb'), or None."""
    m = _VRAM.search(normalise(text))
    return int(m.group(1)) if m else None


def is_excluded(text: str) -> bool:
    return bool(_EXCLUDE.search(normalise(text)))


class Matcher:
    """Resolves titles to watchlist rows by exact chip key (+ VRAM when needed)."""

    def __init__(self, watchlist: Sequence[WatchlistProduct]):
        self.watchlist: List[WatchlistProduct] = list(watchlist)
        self._by_key: Dict[tuple, List[int]] = {}
        self._keyless: List[str] = []
        for i, wp in enumerate(self.watchlist):
            key = chip_key(wp["model"], wp["category"])
            if key is None:
                self._keyless.append(wp["model"])
                continue
            self._by_key.setdefault((wp["category"], key), []).append(i)

    def collisions(self) -> List[str]:
        problems = [f"{m}: model name yields no chip key" for m in self._keyless]
        for (category, key), rows in self._by_key.items():
            if len(rows) < 2:
                continue
            vrams = [self.watchlist[i].get("vram_gb") for i in rows]
            if category != "gpu" or None in vrams or len(set(vrams)) != len(vrams):
                models = ", ".join(self.watchlist[i]["model"] for i in rows)
                problems.append(f"{key}: rows share a key without distinct VRAM ({models})")
        return problems

    def resolve(self, title: str, category: str, extra_text: str = "") -> Optional[int]:
        """Index of the single watchlist row ``title`` is, or None."""
        if is_excluded(title):
            return None
        key = chip_key(title, category)
        if key is None:
            return None
        rows = self._by_key.get((category, key), [])
        if not rows:
            return None
        if category != "gpu":
            return rows[0] if len(rows) == 1 else None
        vram = parse_vram(title) or parse_vram(extra_text)
        if vram is None:
            # One memory size on sale: the key alone is unambiguous. Several:
            # guessing would file an 8GB card under the 16GB product (#2).
            return rows[0] if len(rows) == 1 else None
        same = [i for i in rows if self.watchlist[i].get("vram_gb") == vram]
        return same[0] if len(same) == 1 else None
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest unit_testing/test_chip_key.py -q`

Expected: the unit tests pass. The corpus tests for the five **new** models fail with `got None`, and so do `test_multi_vram_line_without_vram_is_unmatched` and `test_vram_falls_back_to_extra_text`, because those watchlist rows arrive in Task 3. Mark exactly those parametrised cases `xfail(strict=True, reason="rows added in Task 3")`, **or** do Task 3's CSV step first. Recommended: do Task 3 Step 1 (the CSV edit) now, then run again and everything passes.

- [ ] **Step 6: Check the matcher against every title in the local DB**

The local DB's listings are real titles. This step checks that the new rule only disagrees where the old rule was wrong.

```bash
python - <<'EOF'
import sqlite3
from db.watchlist import load_watchlist
from scraper.chip_key import Matcher
m = Matcher(load_watchlist(strict=True))
con = sqlite3.connect("db/trackaroo.db")
rows = con.execute("SELECT p.category, p.model, l.variant_name FROM retailer_listings l JOIN products p ON p.id=l.product_id WHERE l.variant_name IS NOT NULL")
for cat, model, title in rows:
    i = m.resolve(title, cat)
    new = m.watchlist[i]["model"] if i is not None else None
    if new != model:
        print(f"{model!r:32} -> {new!r:32} {title}")
EOF
```

Expected: every line printed is one of these:
- a #1/#2 mis-file (5500GT, 5600GT, 5800XT, 5900XT, 7700X3D, 9950X3D2, 9070 GRE, 9070 XT under the 9070, 245K, 8GB 5060 Ti / 9060 XT, 6GB 3050, AI Box);
- a title with no VRAM for a multi-size line.

**Any other line is a regex bug.** Add that title to `titles.csv` with the right expectation, fix the pattern, and re-run. Paste the final output into the PR description.

- [ ] **Step 7: Commit**

```bash
git add scraper/chip_key.py unit_testing/fixtures/titles.csv unit_testing/test_chip_key.py
git commit -m "feat(matching): canonical chip-key matcher with a real-title corpus (#1, #2)"
```

---

### Task 2: All three scrapers match through `Matcher`

**Files:**
- Modify: `scraper/scorptec.py` (`match_product` at `:234-285`, the loop in `scrape_scorptec` at `:299-345`)
- Modify: `scraper/umart.py` (the loop at `:223-264`)
- Modify: `scraper/pccg.py` (`match_product` at `:86-125`, the loop in `scrape_category` at `:640-680`)
- Modify: `unit_testing/test_matching.py`
- Modify: `unit_testing/test_watchlist_validation.py:146-171`

**Interfaces:**
- Consumes: `Matcher`, `is_excluded` from Task 1.
- Produces: `scorptec.match_product(name, desc, wp) -> bool` and `pccg.match_product(name, wp) -> bool` keep their signatures. They are thin wrappers: `Matcher([wp]).resolve(name, wp["category"], desc) == 0`.

- [ ] **Step 1: Write the failing tests**

Append to `unit_testing/test_matching.py`:

```python
class TestChipKeyWiring:
    """#1: suffixed siblings must not be absorbed; one listing, one product."""

    def test_scorptec_5500_rejects_5500gt(self):
        wp = _make_watchlist_cpu("Ryzen 5 5500", ["ryzen 5 5500"], cores=6)
        assert not scorptec_match("amd ryzen 5 5500gt desktop processor", "", wp)

    def test_pccg_5070_ti_rejects_5070_ti_super(self):
        wp = _make_watchlist_gpu("GeForce RTX 5070 Ti", ["rtx 5070 ti"], vram_gb=16)
        assert not pccg_match("ASUS GeForce RTX 5070 Ti SUPER 24GB", wp)

    def test_scorptec_9070_rejects_gre(self):
        wp = _make_watchlist_gpu("Radeon RX 9070", ["rx 9070"], vram_gb=16)
        assert not scorptec_match("sapphire pulse radeon rx 9070gre 12gb", "", wp)

    def test_pccg_never_claims_one_listing_for_two_products(self, monkeypatch):
        from scraper import pccg
        watchlist = [
            _make_watchlist_gpu("GeForce RTX 4070 Ti", ["rtx 4070 ti"], vram_gb=12),
            _make_watchlist_gpu("GeForce RTX 4070 Ti Super", ["rtx 4070 ti super"], vram_gb=16),
        ]
        for wp in watchlist:
            wp.update(brand="NVIDIA", gen_tier="current-1")
        monkeypatch.setattr(pccg, "algolia_fetch_catalogue", lambda _f: [
            {"name": "ASUS GeForce RTX 4070 Ti Super 16GB", "price": "1299", "url": "https://x/1"},
        ])
        results, _matched, _tripped = pccg.scrape_category("gpu", watchlist)
        assert [r["watchlist_model"] for r in results] == ["GeForce RTX 4070 Ti Super"]
```

Delete `TestTheRealWatchlistIsClean.test_no_base_model_alias_outranks_its_own_variant` from `test_watchlist_validation.py`. The alias-ordering trap no longer exists, and `test_chip_key.py::test_every_watchlist_row_has_a_key_and_no_collisions` replaces it. Update the docstring of the class to say so.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest unit_testing/test_matching.py -q -k ChipKeyWiring`
Expected: 4 FAIL. The substring matcher accepts the GT, SUPER and GRE titles, and PCCG returns two results.

- [ ] **Step 3: Rewire Scorptec**

In `scraper/scorptec.py`:
- Add `from scraper.chip_key import Matcher`.
- Replace the body of `match_product` after its docstring with:

```python
    if _is_bundle_product(scraped_name, scraped_desc):
        return False
    return Matcher([watchlist_product]).resolve(
        scraped_name, watchlist_product["category"], scraped_desc
    ) == 0
```

Update the docstring: matching is exact chip-key equality (see `scraper/chip_key.py`), and search terms are no longer used to match.

In `scrape_scorptec`:
1. Delete the `watchlist_order` sort and its comment.
2. Build `matcher = Matcher(watchlist)` once, before the category loop.
3. Replace the inner `for i in watchlist_order:` loop with:

```python
            category = cat_key.split("_", 1)[0]  # "cpu_amd_am4" -> "cpu"
            i = matcher.resolve(scraped["name"], category, scraped.get("full_description", ""))
            if i is None:
                continue
            wp = watchlist[i]
            match_dict = { ...unchanged... }
            all_matches.setdefault(i, []).append(match_dict)
```

Also update the function docstring: drop the "LONGER primary search terms first" paragraph.

- [ ] **Step 4: Rewire Umart**

In `scraper/umart.py`:
- Change `from scraper.scorptec import match_product` to `from scraper.chip_key import Matcher`.
- Delete `watchlist_order`.
- Build `matcher = Matcher(watchlist)`.
- Replace the inner loop with the following. Keep the existing results dict fields unchanged.

```python
        for product in scraped:
            i = matcher.resolve(product["name"], category, product.get("full_description", ""))
            if i is None:
                continue
            wp = watchlist[i]
            results.append({ ...unchanged fields... })
            matched_ids.add(i)
```

Umart previously got bundle exclusion through `scorptec.match_product`. `Matcher.resolve` covers it via `is_excluded` ("bundle", "combo").

- [ ] **Step 5: Rewire PCCG**

In `scraper/pccg.py`:
- Add `from scraper.chip_key import Matcher`.
- Replace the body of `match_product` after its docstring with:

```python
    if _is_bundle_product(scraped_name):
        return False
    return Matcher([watchlist_product]).resolve(scraped_name, watchlist_product["category"]) == 0
```

In `scrape_category`, replace the per-watchlist loop (the `sorted_indices` loop through `all_matches.setdefault(...)`) with a per-product loop. Each product now resolves to at most one row:

```python
    matcher = Matcher(category_watchlist)
    all_matches: dict[int, list[Dict[str, Any]]] = {}
    for prod in catalogue:
        if _is_bundle_product(prod["name"], prod.get("url", "")):
            continue
        local = matcher.resolve(prod["name"], category)
        if local is None:
            continue
        wp = category_watchlist[local]
        global_idx = model_to_global.get(wp["model"])
        if global_idx is None:
            continue
        price = _parse_price(prod["price"])
        if not price:
            continue
        all_matches.setdefault(global_idx, []).append({ ...unchanged fields... })
```

Do not touch the Algolia search-budget code: `search_terms` still drive the queries.

- [ ] **Step 6: Run the full Python suite**

Run: `python -m pytest -q`

Expected: PASS. Old `test_matching.py` cases that encoded the substring behaviour may now fail. For each failure, decide whether it asserted a mis-file: if it did, invert or delete it with a comment citing #1. Examples are "vram guard allows correct match" for a title without VRAM on a single-size line, which should still pass, and any test expecting `5060 ti` to match an 8GB title, which should flip. `test_umart_wiring.py` and `test_scraper.py` fixtures may use titles like "RTX 5070"; they should still pass.

- [ ] **Step 7: Commit**

```bash
git add scraper/ unit_testing/
git commit -m "fix(matching): all scrapers resolve through the chip-key matcher; PCCG claims each listing once (#1)"
```

---

### Task 3: Watchlist rows for the split variants, and seed syncs specs

**Files:**
- Modify: `db/watchlist.csv`
- Modify: `seed.py:86-110` (`seed_products`)
- Modify: `unit_testing/test_seed.py:55-70`, `unit_testing/test_watchlist_validation.py:144`
- Test: `unit_testing/test_seed.py`

**Interfaces:**
- Produces: watchlist models `GeForce RTX 5060 Ti 8GB` (8GB, current), `GeForce RTX 3050 6GB` (6GB, current-2), `Radeon RX 9060 XT 8GB` (8GB, current), `Radeon RX 9070 GRE` (12GB, current), `Core Ultra 5 245K` (14c, current). There are 105 rows: 55 CPU, 50 GPU.

- [ ] **Step 1: Add the rows**

Insert each row next to its sibling in `db/watchlist.csv`:

```csv
cpu,Intel,Core Ultra 5 245K,14c,current,"core ultra 5 245k|ultra 5 245k|245k intel"
gpu,NVIDIA,GeForce RTX 3050 6GB,6GB,current-2,"rtx 3050 6gb|rtx 3050|3050 nvidia"
gpu,NVIDIA,GeForce RTX 5060 Ti 8GB,8GB,current,"rtx 5060 ti 8gb|rtx 5060 ti|5060ti"
gpu,AMD,Radeon RX 9060 XT 8GB,8GB,current,"rx 9060 xt 8gb|rx 9060 xt|9060xt"
gpu,AMD,Radeon RX 9070 GRE,12GB,current,"rx 9070 gre|9070gre|9070 gre amd"
```

Update the header comment: remove the "alias ordering rule" sentence. Add: "Matching is exact chip-key equality (scraper/chip_key.py). Rows sharing a chip key must differ in VRAM. Aliases only drive PCCG search queries."

- [ ] **Step 2: Write the failing seed test**

Add to `unit_testing/test_seed.py`. Follow the file's existing fixture that builds a temp DB via `init_db`; reuse its helper for an in-memory/temp DB.

```python
def test_existing_product_spec_is_synced_from_csv(tmp_path):
    """#2: Arc B570 sat at 12GB in the DB after the CSV said 10GB."""
    conn = init_db(tmp_path / "t.db")
    seed_products(conn, [{"category": "gpu", "brand": "Intel", "model": "Arc B570",
                          "vram_gb": 12, "cores": None, "generation_tier": "current"}])
    stats = seed_products(conn, [{"category": "gpu", "brand": "Intel", "model": "Arc B570",
                                  "vram_gb": 10, "cores": None, "generation_tier": "current"}])
    assert stats["updated"] == 1
    assert conn.execute("SELECT vram_gb FROM products WHERE model='Arc B570'").fetchone()[0] == 10
```

Check the dict keys `seed_products` actually receives: see `seed.load_watchlist` at `:56`. Match them. The test above assumes `vram_gb`, `cores` and `generation_tier`.

Update the pinned counts to 105 / 55 / 50, with a comment line: "105 on 28-Sep-2026: 245K and the four memory/GRE variants (#1, #2)".

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest unit_testing/test_seed.py -q`
Expected: the new test fails with `assert 0 == 1`.

- [ ] **Step 4: Sync `vram_gb` and `cores` in `seed_products`**

Replace the tier-only sync block (`:95-110`) with:

```python
        if existing:
            # The watchlist is the source of truth for tier AND the spec facts
            # (vram_gb, cores): a correction there must reach existing rows.
            # Arc B570 sat at 12GB in the DB for a month because only the tier
            # was synced (#2). Identity columns are never touched.
            current = conn.execute(
                "SELECT generation_tier, vram_gb, cores FROM products WHERE id = ?", (existing[0],)
            ).fetchone()
            wanted = (p["generation_tier"], p.get("vram_gb"), p.get("cores"))
            if tuple(current) != wanted:
                stats["updated"] += 1
                if not dry_run:
                    conn.execute(
                        "UPDATE products SET generation_tier = ?, vram_gb = ?, cores = ? WHERE id = ?",
                        (*wanted, existing[0]),
                    )
            else:
                stats["skipped"] += 1
            continue
```

- [ ] **Step 5: Run the full Python suite**

Run: `python -m pytest -q`

Expected: PASS, including every `test_chip_key.py` corpus case (remove any Task 1 `xfail` marks now). `sync_specs` tests may count products; update pinned counts the same way. The new rows having no spec record is expected: the spec panel shows nothing until `sync_specs` maps them.

- [ ] **Step 6: Commit**

```bash
git add db/watchlist.csv seed.py unit_testing/
git commit -m "feat(watchlist): split 8GB/6GB variants and RX 9070 GRE, add 245K; seed syncs specs (#2, #21)"
```

---

### Task 4: `repair_listings.py` moves existing mis-filed listings

**Files:**
- Create: `repair_listings.py`
- Create: `unit_testing/test_repair_listings.py`
- Modify: `deploy/bootstrap-data.sh:97-98`
- Modify: `DEPLOYMENT.md`, adding a short "Repair mis-filed listings" section after the redeploy steps

**Interfaces:**
- Consumes: `Matcher` (Task 1), `backup_db.backup_database(db_path=...)`, `db.watchlist.load_watchlist`.
- Produces:
  - `plan_repairs(conn, watchlist) -> List[Repair]`, where `Repair` is a dataclass `(listing_id, retailer, title, from_model, to_model | None)`
  - `apply_repairs(conn, repairs) -> int`
  - CLI: `python repair_listings.py [--apply] [--db PATH]`

**Behaviour:**
- For every listing with a `variant_name` whose product is **tracked**, resolve the title.
- If the title resolves to a *different* tracked product, re-point it.
- If it resolves to nothing, move it to a per-category holding product, `"Unmatched CPU listing"` or `"Unmatched GPU listing"` (brand `Unmatched`, `tracked = 0`), and set `status = 'stale'`. This takes its snapshots out of the wrong product's history and all-time low without deleting anything. It also keeps them reachable for the discovery report (#16).
- Listings whose current product is untracked are left alone, which makes the script idempotent.

- [ ] **Step 1: Write the failing tests**

```python
"""repair_listings: re-point mis-filed listings, never delete a snapshot (#1, #2)."""
import sqlite3
from pathlib import Path

import pytest

import repair_listings as rl
from scraper.chip_key import Matcher  # noqa: F401  (import check)

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

WATCHLIST = [
    {"category": "cpu", "brand": "AMD", "model": "Ryzen 5 5500", "vram_gb": None, "cores": 6},
    {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5060 Ti", "vram_gb": 16, "cores": None},
    {"category": "gpu", "brand": "NVIDIA", "model": "GeForce RTX 5060 Ti 8GB", "vram_gb": 8, "cores": None},
]


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    c.executescript(SCHEMA.read_text(encoding="utf-8"))
    for wp in WATCHLIST:
        c.execute("INSERT INTO products (category, brand, model, vram_gb, cores) VALUES (?,?,?,?,?)",
                  (wp["category"], wp["brand"], wp["model"], wp["vram_gb"], wp["cores"]))
    pid = {m: i for i, m in c.execute("SELECT id, model FROM products")}
    rows = [
        (pid["Ryzen 5 5500"], "amd ryzen 5 5500 desktop processor"),     # correct
        (pid["Ryzen 5 5500"], "amd ryzen 5 5500gt desktop processor"),   # untracked sibling
        (pid["GeForce RTX 5060 Ti"], "palit geforce rtx 5060 ti dual 8g"),  # wrong variant
    ]
    for n, (product_id, title) in enumerate(rows):
        c.execute("INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url) VALUES (?,?,?,?)",
                  (product_id, "scorptec", title, f"https://x/{n}"))
        c.execute("INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud) VALUES (last_insert_rowid(), '2026-09-01', 100)")
    c.commit()
    return c


def test_plan_finds_both_misfiles(conn):
    plan = rl.plan_repairs(conn, WATCHLIST)
    assert {(r.title, r.to_model) for r in plan} == {
        ("amd ryzen 5 5500gt desktop processor", None),
        ("palit geforce rtx 5060 ti dual 8g", "GeForce RTX 5060 Ti 8GB"),
    }


def test_apply_moves_listings_and_keeps_snapshots(conn):
    before = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    rl.apply_repairs(conn, rl.plan_repairs(conn, WATCHLIST))
    assert conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == before
    moved = dict(conn.execute(
        "SELECT l.variant_name, p.model FROM retailer_listings l JOIN products p ON p.id = l.product_id"))
    assert moved["palit geforce rtx 5060 ti dual 8g"] == "GeForce RTX 5060 Ti 8GB"
    assert moved["amd ryzen 5 5500gt desktop processor"] == "Unmatched CPU listing"
    status, tracked = conn.execute(
        "SELECT l.status, p.tracked FROM retailer_listings l JOIN products p ON p.id=l.product_id "
        "WHERE l.variant_name LIKE '%5500gt%'").fetchone()
    assert (status, tracked) == ("stale", 0)


def test_second_run_is_a_no_op(conn):
    rl.apply_repairs(conn, rl.plan_repairs(conn, WATCHLIST))
    assert rl.plan_repairs(conn, WATCHLIST) == []


def test_cli_defaults_to_dry_run(conn, tmp_path, capsys):
    conn.close()
    rl.main(["--db", str(tmp_path / "t.db")])
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "5500gt" in out
    c = sqlite3.connect(tmp_path / "t.db")
    assert c.execute("SELECT COUNT(*) FROM products WHERE brand='Unmatched'").fetchone()[0] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest unit_testing/test_repair_listings.py -q`
Expected: `ModuleNotFoundError: No module named 'repair_listings'`.

- [ ] **Step 3: Implement `repair_listings.py`**

```python
"""Re-point listings the old substring matcher filed under the wrong product.

Fixing the matcher (scraper/chip_key.py) only affects new scrapes:
ingest.find_or_create_listing never changes an existing listing's product. This
applies the same matcher to every listing already in the DB.

  * resolves to a different tracked product -> re-pointed there;
  * resolves to nothing (an untracked part such as a 5500GT, or an eGPU box)
    -> moved to a tracked=0 "Unmatched <CAT> listing" holding product and
       marked stale, so its prices leave the wrong product's history.

Snapshots are never deleted: they are correct prices for the real part.
Dry run by default; --apply takes a backup first.

    python repair_listings.py            # show what would change
    python repair_listings.py --apply    # back up, then change it
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from backup_db import backup_database
from config import DB_PATH
from db.watchlist import WatchlistProduct, load_watchlist
from scraper.chip_key import Matcher

LOGGER = logging.getLogger(__name__)
HOLDING_BRAND = "Unmatched"


@dataclass(frozen=True)
class Repair:
    listing_id: int
    retailer: str
    title: str
    from_model: str
    to_model: Optional[str]  # None -> holding product


def _holding_model(category: str) -> str:
    return f"Unmatched {category.upper()} listing"


def plan_repairs(conn: sqlite3.Connection, watchlist: Sequence[WatchlistProduct]) -> List[Repair]:
    matcher = Matcher(watchlist)
    rows = conn.execute(
        """SELECT l.id, l.retailer, l.variant_name, p.category, p.model
           FROM retailer_listings l JOIN products p ON p.id = l.product_id
           WHERE p.tracked = 1 AND l.variant_name IS NOT NULL
           ORDER BY l.id"""
    ).fetchall()
    repairs: List[Repair] = []
    for listing_id, retailer, title, category, model in rows:
        idx = matcher.resolve(title, category)
        target = matcher.watchlist[idx]["model"] if idx is not None else None
        if target != model:
            repairs.append(Repair(listing_id, retailer, title, model, target))
    return repairs


def _product_id(conn: sqlite3.Connection, category: str, model: str, holding: bool) -> int:
    row = conn.execute(
        "SELECT id FROM products WHERE category = ? AND model = ?", (category, model)
    ).fetchone()
    if row:
        return row[0]
    if not holding:
        raise LookupError(f"{model!r} is in the watchlist but not the DB: run seed.py first")
    cur = conn.execute(
        "INSERT INTO products (category, brand, model, tracked) VALUES (?, ?, ?, 0)",
        (category, HOLDING_BRAND, model),
    )
    return cur.lastrowid


def apply_repairs(conn: sqlite3.Connection, repairs: Sequence[Repair]) -> int:
    for r in repairs:
        category = conn.execute(
            "SELECT p.category FROM retailer_listings l JOIN products p ON p.id = l.product_id WHERE l.id = ?",
            (r.listing_id,),
        ).fetchone()[0]
        if r.to_model is None:
            pid = _product_id(conn, category, _holding_model(category), holding=True)
            conn.execute(
                "UPDATE retailer_listings SET product_id = ?, status = 'stale' WHERE id = ?",
                (pid, r.listing_id),
            )
        else:
            pid = _product_id(conn, category, r.to_model, holding=False)
            conn.execute("UPDATE retailer_listings SET product_id = ? WHERE id = ?", (pid, r.listing_id))
    conn.commit()
    return len(repairs)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="back up, then write the changes")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn = sqlite3.connect(str(args.db))
    repairs = plan_repairs(conn, load_watchlist(strict=True))
    print(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(repairs)} listing(s) to re-point")
    for r in repairs:
        print(f"  [{r.retailer:8}] {r.from_model!r} -> {r.to_model or 'UNMATCHED (stale)'!r}  {r.title}")
    if args.apply and repairs:
        conn.close()
        backup = backup_database(db_path=args.db)
        print(f"Backup written: {backup}")
        conn = sqlite3.connect(str(args.db))
        print(f"Re-pointed {apply_repairs(conn, repairs)} listing(s)")
    conn.close()


if __name__ == "__main__":
    main()
```

The tests pass the watchlist as plain dicts without `search_terms`. `Matcher` only reads `model`, `category` and `vram_gb`, so that works.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest unit_testing/test_repair_listings.py -q`
Expected: 4 PASS.

- [ ] **Step 5: Dry run against the local DB and attach the output**

Run: `python repair_listings.py`

Expected: the output lists the #1 and #2 cases (5500GT, 5600GT, 5800XT, 5900XT, 7700X3D, 9950X3D2, GRE and XT under the 9070, 245K, 8GB 5060 Ti / 9060 XT, 6GB 3050, AI Box). Do **not** `--apply` to prod here. The local DB is not live data, so running `--apply` locally only for a before/after screenshot is fine. Paste the dry-run output into the PR.

- [ ] **Step 6: Run the repair after a fresh hydrate**

In `deploy/bootstrap-data.sh`, after `TRACKAROO_DATA_DIR=/app/seed-data python ingest.py` add:

```sh
# Old snapshot JSON carries the matcher's old decisions; re-apply today's rules
# so a rebuilt DB does not resurrect mis-filed listings (#1, #2).
python seed.py
python repair_listings.py --apply
```

`test_shell_scripts.py` may assert the script's contents or lint it. Run it.

In `DEPLOYMENT.md`, add a section with these steps:
1. After pulling this change, run `docker exec trackaroo python seed.py`.
2. Run `docker exec trackaroo python repair_listings.py` (dry run) and review the output.
3. Run it again with `--apply`.

The container entrypoint already runs `seed.py` on boot.

- [ ] **Step 7: Full gate and commit**

Run: `python -m pytest -q`
Expected: PASS.

```bash
git add repair_listings.py unit_testing/test_repair_listings.py deploy/bootstrap-data.sh DEPLOYMENT.md
git commit -m "feat(pipeline): repair_listings.py re-points mis-filed listings, backup-first, idempotent (#1, #2)"
```

---

### Task 5: A listing that stopped being seen cannot set a price (#4)

**Files:**
- Modify: `web/src/lib/constants.ts`
- Modify: `web/src/lib/listingsPanel.ts`
- Modify: `web/src/lib/productHeadline.ts:35`
- Modify: `web/src/lib/offers.ts:9-20` (`offerTier`)
- Modify: `web/src/lib/deals.ts` (`dealToOffer` adds `stale: false`)
- Modify: `web/src/lib/server/repos.ts` (`ProductHistory` + `getProductHistory` at `:685`, and the listing query in `getComparisonData` at about `:1112`)
- Modify: `web/src/lib/components/OfferRow.svelte:83-87`
- Modify: `web/src/lib/components/OfferList.svelte:34`, `web/src/routes/product/[id]/+page.svelte:77`
- Test: `web/test/listingsPanel.test.ts`, `web/test/productHeadline.test.ts`, `web/test/repos.test.ts`, `web/test/helpers/offers.ts`

**Interfaces:**
- Produces:
  - `ListingDisplay.stale: boolean`, which is true when `status === 'stale'` OR `lastSeen` is more than `STALE_LISTING_DAYS` before the listing's retailer's latest snapshot
  - `toListingDisplays(series, productBrand, selected, retailerLatest: Record<string, string> = {})`
  - `ProductHistory.retailerLatest: Record<string, string>`
  - `STALE_LISTING_DAYS = 7`, mirroring `config.STALE_LISTING_DAYS`

- [ ] **Step 1: Write the failing tests**

In `web/test/listingsPanel.test.ts`, using the file's `series`/`snapshot` helpers:

```ts
describe('stale listings (#4)', () => {
	it('a status=stale listing is not in stock even if its last snapshot said so', () => {
		const s = series(9, 'ASUS TUF RTX 5090', [snapshot('2026-08-20', 7499, 'in_stock')], 'stale');
		const [d] = toListingDisplays([s], 'NVIDIA', new Set());
		expect(d.stale).toBe(true);
		expect(d.inStock).toBe(false);
	});

	it('an active listing unseen for more than 7 days before its retailer latest is stale', () => {
		const s = series(9, 'ASUS TUF RTX 5090', [snapshot('2026-08-20', 7499, 'in_stock')]);
		const [d] = toListingDisplays([s], 'NVIDIA', new Set(), { scorptec: '2026-09-28' });
		expect(d.stale).toBe(true);
		expect(d.inStock).toBe(false);
	});

	it('a listing seen within the window stays buyable', () => {
		const s = series(9, 'ASUS TUF RTX 5090', [snapshot('2026-09-25', 8999, 'in_stock')]);
		const [d] = toListingDisplays([s], 'NVIDIA', new Set(), { scorptec: '2026-09-28' });
		expect(d.stale).toBe(false);
		expect(d.inStock).toBe(true);
	});

	it('priceRange ignores stale listings', () => {
		const ghost = series(1, 'ghost', [snapshot('2026-08-20', 7499, 'in_stock')], 'stale');
		const live = series(2, 'live', [snapshot('2026-09-28', 8999, 'in_stock')]);
		expect(priceRange(toListingDisplays([ghost, live], 'NVIDIA', new Set()))).toEqual({ min: 8999, max: 8999 });
	});
});
```

In `web/test/productHeadline.test.ts`:

```ts
it('never takes the headline from a stale listing (#4)', () => {
	const offers = [
		offer({ listingId: 1, latestPrice: 7499, stale: true, inStock: false }),
		offer({ listingId: 2, latestPrice: 8999 })
	];
	expect(buildHeadline(offers, [], { avg30: null, avg30Points: 0 }).currentPrice).toBe(8999);
});
```

Match the `ProductStats` shape used in that file's existing tests.

In `web/test/repos.test.ts`, following that file's seeded-DB pattern:
- Assert that `getProductHistory(db, id).retailerLatest` has one entry per retailer, equal to that retailer's max `snapshot_date`.
- Assert that `getComparisonData` excludes a listing with `status='stale'`.

In `web/test/helpers/offers.ts`, add `stale: false,` to the default object.

- [ ] **Step 2: Run to verify they fail**

Run (from `web/`): `npm test -- listingsPanel productHeadline repos`
Expected: FAIL (`stale` is undefined, and `retailerLatest` is undefined).

- [ ] **Step 3: Implement**

`constants.ts`:

```ts
// Mirrors config.STALE_LISTING_DAYS: a listing unseen this many days before its
// retailer's latest snapshot is treated as gone even before the pipeline's
// check_stale_listings flips its status (#4).
export const STALE_LISTING_DAYS = 7;
```

`listingsPanel.ts`:
- Add `stale: boolean;` to `ListingDisplay`, with a comment: "Unseen for STALE_LISTING_DAYS+ or marked stale by the pipeline. Not buyable."
- Import `STALE_LISTING_DAYS`.
- Add the `retailerLatest: Record<string, string> = {}` parameter.
- Inside the map:

```ts
		const lastSeen = last?.snapshot_date ?? null;
		const retailerLast = retailerLatest[s.listing.retailer];
		const unseenTooLong =
			lastSeen !== null &&
			retailerLast !== undefined &&
			(Date.parse(retailerLast) - Date.parse(lastSeen)) / 86_400_000 > STALE_LISTING_DAYS;
		const stale = !delisted && (s.listing.status === 'stale' || unseenTooLong);
		...
			stale,
			inStock: !delisted && !stale && last?.stock_status === 'in_stock',
```

In `priceRange`, change the skip to `if (l.delisted || l.stale || l.latestPrice === null) continue;`.

`productHeadline.ts:35`: `if (!o.inStock || o.delisted || o.stale || o.latestPrice === null) continue;`

`offers.ts` `offerTier`: `if (o.delisted || o.stale) return 'delisted';`. The tier sorts them last, and the name stays.

`deals.ts` `dealToOffer`: add `stale: false,`.

`repos.ts`:
- Add `retailerLatest: Record<string, string>;` to `ProductHistory`.
- In `getProductHistory`, before `return`:

```ts
	const retailerLatest = Object.fromEntries(
		(
			db
				.prepare(
					`SELECT l.retailer AS retailer, MAX(s.snapshot_date) AS latest
					 FROM price_snapshots s JOIN retailer_listings l ON l.id = s.retailer_listing_id
					 GROUP BY l.retailer`
				)
				.all() as Array<{ retailer: string; latest: string }>
		).map((r) => [r.retailer, r.latest])
	);
```

  Then add `retailerLatest,` to the returned object.
- In `getComparisonData`'s listing query, add `AND l.status = 'active'` to the `WHERE`.

`OfferList.svelte:34` and `product/[id]/+page.svelte:77`: pass `data.retailerLatest` (or a new `retailerLatest` prop on `OfferList`, threaded from the page) as the fourth argument.

`OfferRow.svelte:83-87`:

```svelte
		{#if offer.delisted}
			<Badge tone="stale" label="Delisted" />
		{:else if offer.stale}
			<Badge tone="stale" label={offer.lastSeen ? `Not seen since ${formatShortDate(offer.lastSeen)}` : 'Not seen recently'} />
		{:else}
```

If `formatShortDate` does not exist in `formats.ts`, use the date helper there that renders `12 Sep`, or add:

```ts
export function formatShortDate(isoDate: string): string {
	const [y, m, d] = isoDate.split('-').map(Number);
	return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-AU', { day: 'numeric', month: 'short', timeZone: 'UTC' });
}
```

- [ ] **Step 4: Run the web gate**

Run (from `web/`): `npm run check && npm test`
Expected: 0 errors and all tests PASS. Fix any component test that builds a `ListingDisplay` literal by adding `stale: false`.

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "fix(web): a listing that stopped being seen can't set the headline or compare price (#4)"
```

---

### Task 6: /deals shows only real deals, once each, with honest labels (#6)

**Files:**
- Modify: `web/src/lib/constants.ts`
- Modify: `web/src/lib/server/repos.ts` (`DealCandidate`, `getDealCandidates` `:883-997`; window arithmetic at `:610`, `:638`, `:966`)
- Modify: `web/src/lib/deals.ts`
- Modify: `web/src/routes/deals/+page.server.ts`, `web/src/routes/deals/+page.svelte`
- Modify: `web/src/lib/formats.ts` (`formatSeenDate`)
- Modify: `web/src/lib/components/OfferRow.svelte`
- Test: `web/test/deals.test.ts`, `web/test/formats.test.ts`, `web/test/repos.test.ts`, `web/test/components.test.ts`, `web/e2e/app.spec.ts`

**Interfaces:**
- Produces:
  - constants `DEAL_MIN_PCT = 2`, `DEAL_MIN_AUD = 10`, `EARNED_LOW_RISE_PCT = 3`
  - `DealCandidate.windowHigh: number | null`, the highest daily-cheapest price in the window
  - `DealCandidate.historyStart: string | null`, the product's first in-stock snapshot date
  - `Deal.savingAud: number | null` and `Deal.earnedLow: boolean`
  - `belowAverage(deals)` applies both floors
  - `atAllTimeLow(deals)` returns earned lows **not already** in `belowAverage`
  - `shownDeals(deals)` is the union of the two lists, and the facets count it
  - `formatSeenDate(isoDate: string, today: string) -> string`, which returns 'today', 'yesterday', 'N days ago' or '12 Sep'
  - `OfferRow` gets new optional props `saving?: number | null` and `lowSince?: string | null`

- [ ] **Step 1: Write the failing tests**

`web/test/deals.test.ts`. Build candidates with the file's existing helper; extend it with `windowHigh` and `historyStart` defaults of `null`.

```ts
describe('deal floors (#6)', () => {
	it('drops a -0.1% ($0.13) move', () => {
		const d = toDeals([candidate({ price: 129.87, avg30: 130, avg30Points: 30 })]);
		expect(belowAverage(d)).toEqual([]);
	});
	it('drops 3% when it is under $10', () => {
		const d = toDeals([candidate({ price: 97, avg30: 100, avg30Points: 30 })]);
		expect(belowAverage(d)).toEqual([]);
	});
	it('keeps 2% and $10 together', () => {
		const d = toDeals([candidate({ price: 490, avg30: 500, avg30Points: 30 })]);
		expect(belowAverage(d).map((x) => x.savingAud)).toEqual([10]);
	});
});

describe('earned all-time low (#6)', () => {
	it('a price that never moved is not a new low', () => {
		const d = toDeals([candidate({ price: 300, avg30: 300, allTimeLow: 300, windowHigh: 300, avg30Points: 30 })]);
		expect(atAllTimeLow(d)).toEqual([]);
	});
	it('a drop from 3%+ higher is an earned low', () => {
		const d = toDeals([candidate({ price: 300, avg30: 302, allTimeLow: 300, windowHigh: 310, avg30Points: 30 })]);
		expect(atAllTimeLow(d)).toHaveLength(1);
	});
	it('a product that is also below average appears only there', () => {
		const d = toDeals([candidate({ price: 450, avg30: 500, allTimeLow: 450, windowHigh: 520, avg30Points: 30 })]);
		expect(belowAverage(d)).toHaveLength(1);
		expect(atAllTimeLow(d)).toEqual([]);
		expect(shownDeals(d)).toHaveLength(1);
		expect(belowAverage(d)[0].earnedLow).toBe(true);
	});
});
```

`web/test/formats.test.ts`:

```ts
describe('formatSeenDate', () => {
	it.each([
		['2026-09-28', 'today'],
		['2026-09-27', 'yesterday'],
		['2026-09-24', '4 days ago'],
		['2026-09-12', '12 Sep']
	])('%s -> %s', (d, out) => expect(formatSeenDate(d, '2026-09-28')).toBe(out));
});
```

`web/test/repos.test.ts`: in the existing `getDealCandidates` describe block, assert:
- `windowHigh` equals the max daily-cheapest in the window of the seeded data;
- `historyStart` equals the product's first in-stock date;
- a product with exactly 30 consecutive in-stock days up to the latest date reports `avg30Points === 30` (not 31).

`web/e2e/app.spec.ts`, in the existing /deals test: the count of `[data-testid="deal-row"]` equals the "All" chip count, and no row text matches `/-0\.\d%/`.

- [ ] **Step 2: Run to verify they fail**

Run (from `web/`): `npm test -- deals formats repos`
Expected: FAIL (`savingAud`, `shownDeals` and `formatSeenDate` are undefined, and `avg30Points` is 31).

- [ ] **Step 3: Constants and query**

`constants.ts`:

```ts
// /deals floors (owner decision 28-Sep-2026, #6): a deal must be at least this
// far below its 30-day average in BOTH percent and dollars.
export const DEAL_MIN_PCT = 2;
export const DEAL_MIN_AUD = 10;
// An all-time low only counts if the price was at least this much higher at
// some point in the window -- a flat line is not a drop.
export const EARNED_LOW_RISE_PCT = 3;
```

`repos.ts` `getDealCandidates`:
- Add to the SELECT, next to `avg30`:

```sql
				(SELECT MAX(dm.price)
				 FROM (
					SELECT ps3.snapshot_date, MIN(ps3.price_aud) AS price
					FROM price_snapshots ps3
					JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
					WHERE l3.product_id = p.id
					  AND ps3.stock_status = 'in_stock'
					  AND ${notBundle('l3')}
					  AND ps3.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), @window)
					GROUP BY ps3.snapshot_date
				 ) dm) AS window_high,
				(SELECT MIN(ps3.snapshot_date)
				 FROM price_snapshots ps3
				 JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
				 WHERE l3.product_id = p.id AND ps3.stock_status = 'in_stock') AS history_start,
```

- Add `window_high: number | null; history_start: string | null;` to the row type.
- Add `windowHigh: r.window_high, historyStart: r.history_start` to the mapping.
- Add both fields to `DealCandidate`.

One window, three labels (the "31-day avg" versus "up to 30 days" versus "21-day" mix): at `:610`, `:638` and `:966` change `` `-${days} days` `` to `` `-${days - 1} days` `` so a 30-day window covers 30 dates, inclusive of today. Do **not** change the movers or sparkline windows at `:498`, `:538`, `:571` and `:1027`.

- [ ] **Step 4: `deals.ts`**

```ts
import { DEAL_MIN_AUD, DEAL_MIN_PCT, EARNED_LOW_RISE_PCT, MIN_HISTORY_POINTS } from './constants';

export interface Deal extends DealCandidate {
	depthPct: number | null;
	// Dollars below the 30-day average. Positive = cheaper.
	savingAud: number | null;
	nearAllTimeLow: boolean;
	// Near the low AND the price was EARNED_LOW_RISE_PCT higher inside the
	// window: a drop, not a flat line (#6).
	earnedLow: boolean;
}

export function isEarnedLow(c: DealCandidate): boolean {
	return (
		isNearAllTimeLow(c.price, c.allTimeLow) &&
		c.windowHigh !== null &&
		c.windowHigh >= c.price * (1 + EARNED_LOW_RISE_PCT / 100)
	);
}

export function toDeals(candidates: DealCandidate[]): Deal[] {
	return candidates.filter(isEligible).map((c) => ({
		...c,
		depthPct: dealDepthPct(c.price, c.avg30),
		savingAud: c.avg30 === null ? null : Math.round((c.avg30 - c.price) * 100) / 100,
		nearAllTimeLow: isNearAllTimeLow(c.price, c.allTimeLow),
		earnedLow: isEarnedLow(c)
	}));
}

function isRealDeal(d: Deal): boolean {
	return (
		d.depthPct !== null && d.depthPct >= DEAL_MIN_PCT &&
		d.savingAud !== null && d.savingAud >= DEAL_MIN_AUD
	);
}

export function belowAverage(deals: Deal[]): Deal[] {
	return deals.filter(isRealDeal).sort(byDepthDesc);
}

// Earned lows that are NOT already listed above: one row per product (#6).
export function atAllTimeLow(deals: Deal[]): Deal[] {
	return deals.filter((d) => d.earnedLow && !isRealDeal(d)).sort(byDepthDesc);
}

export function shownDeals(deals: Deal[]): Deal[] {
	return deals.filter((d) => isRealDeal(d) || d.earnedLow);
}
```

Update the file header comment to state the floors and the earned-low rule.

- [ ] **Step 5: Page server counts what is shown**

In `routes/deals/+page.server.ts`, replace `const deals = toDeals(getDealCandidates(db));` with:

```ts
	// Facets count the rows the page can actually show, so "All 42" can't sit
	// above 32 rows (28-Sep finding).
	const deals = shownDeals(toDeals(getDealCandidates(db)));
```

Also return `historyStart`: the earliest `historyStart` across candidates, for the subtitle. Import `shownDeals`.

- [ ] **Step 6: Page and row copy**

`formats.ts`:

```ts
// Snapshots are dated, not timed: comparing a 'YYYY-MM-DD' against now() made
// every row say "updated just now" (28-Sep finding). Whole days only.
export function formatSeenDate(isoDate: string, today: string): string {
	const days = Math.round((Date.parse(today) - Date.parse(isoDate)) / 86_400_000);
	if (days <= 0) return 'today';
	if (days === 1) return 'yesterday';
	if (days < 7) return `${days} days ago`;
	return formatShortDate(isoDate);
}

export function todayIso(now: Date = new Date()): string {
	const y = now.getFullYear();
	const m = String(now.getMonth() + 1).padStart(2, '0');
	const d = String(now.getDate()).padStart(2, '0');
	return `${y}-${m}-${d}`;
}
```

`OfferRow.svelte` changes:
1. Add props `saving?: number | null` and `lowSince?: string | null`.
2. Freshness: replace `· updated {formatRelative(offer.lastSeen)}` with `· seen {formatSeenDate(offer.lastSeen, todayIso())}`.
3. When `titleOverride` is set, show the listing under the model name, so a buyer sees "Palit Dual 8G": add `<span class="block truncate text-xs text-text-muted">{titleCase(offer.variantName)}</span>` below the title link, guarded by `{#if titleOverride && offer.variantName}`.
4. Delta: when `saving` is a number, render `{formatSignedAud(-saving)} · {formatPct(deltaPct)} {avgWindowLabel(avgPoints)} ({formatAud(avg30)})` in place of the arrow and percentage alone.
5. When `lowSince` is set, add `<Badge tone="accent" label={`Lowest since ${formatShortDate(lowSince)}`} />`. Use whatever `Badge` tone exists for a positive note; check `Badge.svelte`.
6. The outbound link: change the text to `Buy at {retailerLabel} ↗` and add `aria-label="Buy at {retailerLabel} (opens in a new tab)"`.
7. Add `data-testid="deal-row"` on the root element when `titleOverride` is set.

`routes/deals/+page.svelte`:
- Subtitle: "Cheapest in-stock price at least {DEAL_MIN_PCT}% **and** ${DEAL_MIN_AUD} below its own 30-day average."
- Count line: `{below} below their average · {lows} at a new low`.
- Section 2 heading: "At a new low".
- Section 2 subtitle: "Within {NEAR_ALL_TIME_LOW_PCT}% of the lowest price since tracking began ({formatShortDate(data.historyStart)}), after being at least {EARNED_LOW_RISE_PCT}% higher this month."
- Pass `saving={deal.savingAud}` and `lowSince={deal.earnedLow ? deal.historyStart : null}` to both lists' `OfferRow`.
- Remove the duplicate `mx-auto max-w-6xl px-4 py-6` wrapper: `+layout.svelte` already provides it. Keep a plain `<div>`.

- [ ] **Step 7: Run the web gate**

Run (from `web/`): `npm run check && npm test && npm run test:e2e`

Expected: PASS. Existing tests that expected −0.1% deals, "View →" or "updated" text will fail. Update each one to the new rule and cite #6 in the test name. Homepage deals come from `belowAverage`, so e2e expectations for the homepage "Top deals" may shrink. Check `e2e/seed.mjs` produces at least one ≥2%/≥$10 deal so the section is still exercised, and add one if not.

- [ ] **Step 8: Commit**

```bash
git add web/
git commit -m "fix(deals): 2%+\$10 floor, earned lows, one row per product, honest labels (#6)"
```

---

### Task 7: Close out

- [ ] **Step 1: Full regression gate from a clean tree**

Run:
- `python -m pytest -q` from the repo root
- `npm run check`, `npm test` and `npm run test:e2e` from `web/`

Expected: all green. Record the counts.

- [ ] **Step 2: Local before/after on the local DB**

1. Copy the local DB.
2. Run `python seed.py && python repair_listings.py --apply` on the copy.
3. Start the app against it: `TRACKAROO_DB=<copy> npm run dev` from `web/`.
4. Check:
   - `/product/<5060 Ti id>`: the headline is a 16GB listing.
   - A new `GeForce RTX 5060 Ti 8GB` product exists and has history.
   - `/deals` has no row under 2% / $10, and chip "All" equals the number of rows.
   - The RTX 5090 headline is not a ghost listing.

- [ ] **Step 3: STATUS.md and issues**

- Add a dated "Recent changes" entry to `STATUS.md` with the new test counts.
- Add a "Deploy notes" entry: on redeploy, run `seed.py` then `repair_listings.py` (dry run, review, then `--apply`).
- Comment on #1, #2, #4 and #6 with the commit SHAs. Leave them open until the prod redeploy (roadmap Phase 6) confirms.

```bash
git add STATUS.md
git commit -m "docs: 28-Sep correct-prices changes and redeploy notes"
```
