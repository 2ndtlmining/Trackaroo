# discover_rules.py
"""Pure rules for the discovery report (#16): what is excluded, what is in
scope, and how an untracked part is named and turned into a watchlist row.

The scope table lives in db/generations.toml (#17): a part's chip key maps to
a series through that file's `chips`, and the series position gives its tier.
A series NEWER than any listed (RTX 60, Ryzen 10000) counts as in scope at
'current', so a launch surfaces instead of being silently dropped.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional, Sequence, Tuple

from db.generations import Generations, default_generations
from scraper.chip_key import is_excluded, normalise

_EXTRA_EXCLUDE = re.compile(
    r"\b(?:refurb\w*|open box|ex demo|demo unit|rtx pro|radeon pro|quadro|threadripper|xeon|epyc|workstation)\b"
)


def is_excluded_title(title: str) -> bool:
    return is_excluded(title) or bool(_EXTRA_EXCLUDE.search(normalise(title)))


def _digits(text: str) -> str:
    m = re.match(r"[a-z]?(\d+)", text)
    return m.group(1) if m else ""


def chip_token(category: str, key: str) -> Optional[Tuple[str, str]]:
    """(family, gen) for a chip key, in the terms db/generations.toml's `chips` use."""
    family, _, rest = key.partition(" ")
    digits = _digits(rest)
    if family in ("rtx", "rx"):
        if not digits:
            return None
        # Every GeForce RTX number is d0[5-9]0 (3050..3090, 4060..4090, 5050..5090); anything
        # else ("RTX 6000 Ada", "RTX 4500 Ada", "RTX 5880 Ada") is an Nvidia workstation card.
        if family == "rtx" and not re.fullmatch(r"\d0[5-9]0", digits[:4]):
            return None
        return family, str(int(digits[:4]) // 1000)
    if family == "arc":
        # No letter ("arc", "arc 140v" Lunar Lake iGPU) is a laptop part: out of scope.
        return ("arc", rest[:1]) if rest[:1].isalpha() else None
    if family == "ryzen":
        return ("ryzen", str(int(digits) // 1000)) if digits else None
    if family == "ultra":
        return ("ultra", str(int(digits) // 100)) if digits else None
    if family == "core":
        return ("core", str(int(digits[:2]))) if len(digits) >= 5 else None
    return None


def _newer(gen: str, known: List[str]) -> bool:
    if gen.isdigit() and all(k.isdigit() for k in known):
        return int(gen) > max(int(k) for k in known)
    return gen > max(known)


def series_tier(category: str, key: str, generations: Optional[Generations] = None) -> Optional[str]:
    """In-scope tier for an untracked part, from db/generations.toml.

    A gen listed in a series takes that series' tier (None once it has rolled
    out of scope). A gen NEWER than every listed gen of its family counts as
    'current', so a launch surfaces instead of being dropped; an older unknown
    gen is out of scope.
    """
    gens = generations if generations is not None else default_generations()
    token = chip_token(category, key)
    if token is None:
        return None
    family, gen = token
    series = gens.chip_series(family, gen)
    if series is not None:
        return gens.tier(series.key)
    known = gens.chip_gens(family)
    return "current" if known and _newer(gen, known) else None


def part_key(category: str, key: str, vram: Optional[int]) -> str:
    return f"{key}|{vram}" if category == "gpu" and vram else key


def brand_for(key: str) -> str:
    family = key.split(" ", 1)[0]
    return {"rtx": "NVIDIA", "rx": "AMD", "ryzen": "AMD"}.get(family, "Intel")


def _class_from_titles(titles: Sequence[str], pattern: str) -> Optional[str]:
    found = Counter(m.group(1) for t in titles for m in [re.search(pattern, normalise(t))] if m)
    return found.most_common(1)[0][0] if found else None


def _ryzen_class(code: str) -> str:
    d = int(code[1])
    return "9" if d == 9 else "7" if d >= 7 else "5" if d >= 4 else "3"


def _ultra_class(num: str) -> str:
    t = int(num[1])
    return "5" if t <= 5 else "7" if t <= 7 else "9"


def _core_class(num: str) -> str:
    d = int(num[2])
    return "3" if d <= 3 else "5" if d <= 6 else "7" if d <= 8 else "9"


def model_name(category: str, key: str, titles: Sequence[str]) -> str:
    family, _, rest = key.partition(" ")
    words = rest.split()
    if family == "rtx":
        suffix = {"ti": "Ti", "super": "Super"}
        return "GeForce RTX " + " ".join([words[0]] + [suffix[w] for w in words[1:]])
    if family == "rx":
        return "Radeon RX " + " ".join([words[0]] + [w.upper() for w in words[1:]])
    if family == "arc":
        return f"Arc {rest.upper()}"
    if family == "ryzen":
        code = rest.upper()
        cls = _class_from_titles(titles, r"\bryzen ?([3579])\b") or _ryzen_class(code)
        return f"Ryzen {cls} {code}"
    if family == "ultra":
        m = re.match(r"(\d{3})([a-z]*)( plus)?", rest)
        num, suf, plus = m.group(1), m.group(2).upper(), " Plus" if m.group(3) else ""
        cls = _class_from_titles(titles, r"\bultra ?([3579])\b") or _ultra_class(num)
        return f"Core Ultra {cls} {num}{suf}{plus}"
    if family == "core":
        m = re.match(r"(\d{5})([a-z]*)", rest)
        num, suf = m.group(1), m.group(2).upper()
        cls = _class_from_titles(titles, r"\bi([3579])\b") or _core_class(num)
        return f"Core i{cls}-{num}{suf}"
    return key


def display_name(category: str, key: str, vram: Optional[int], titles: Sequence[str]) -> str:
    base = model_name(category, key, titles)
    return f"{base} {vram}GB" if category == "gpu" and vram else base


def suggested_row(
    category: str, key: str, vram: Optional[int], titles: Sequence[str], vram_in_model: bool
) -> str:
    """A db/watchlist.csv line. CPU cores are rarely in shop titles: '?c' is
    filled from the spec source when the row is added (README)."""
    base = model_name(category, key, titles)
    model = f"{base} {vram}GB" if category == "gpu" and vram and vram_in_model else base
    spec = (f"{vram}GB" if vram else "?GB") if category == "gpu" else "?c"
    tier = series_tier(category, key) or "current"
    return f"{category},{brand_for(key)},{model},{spec},{tier}"
