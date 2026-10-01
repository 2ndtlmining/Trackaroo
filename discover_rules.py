# discover_rules.py
"""Pure rules for the discovery report (#16): what is excluded, what is in
scope, and how an untracked part is named and turned into a watchlist row.

The scope table mirrors docs/ARCHITECTURE.md Part 2 (current, current-1,
current-2 per product line; Intel Arc all in scope). A series NEWER than the
table (RTX 60, Ryzen 5-digit) counts as in scope at 'current', so a launch
surfaces instead of being silently dropped -- update this table and Part 2
together when that happens. test_discover_rules pins the table to
db/watchlist.csv.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional, Sequence

from scraper.chip_key import is_excluded, normalise

_EXTRA_EXCLUDE = re.compile(
    r"\b(?:refurb\w*|open box|ex demo|demo unit|rtx pro|radeon pro|quadro|threadripper|xeon|epyc|workstation)\b"
)

_GPU_TIERS = {
    "rtx": {5: "current", 4: "current-1", 3: "current-2"},
    "rx": {9: "current", 7: "current-1", 6: "current-2"},
}
_RYZEN_TIERS = {9: "current", 8: "current-1", 7: "current-1", 5: "current-2"}
_CORE_TIERS = {14: "current-1", 13: "current-2"}


def is_excluded_title(title: str) -> bool:
    return is_excluded(title) or bool(_EXTRA_EXCLUDE.search(normalise(title)))


def _digits(text: str) -> str:
    m = re.match(r"[a-z]?(\d+)", text)
    return m.group(1) if m else ""


def series_tier(category: str, key: str) -> Optional[str]:
    family, _, rest = key.partition(" ")
    digits = _digits(rest)
    if not digits and family != "arc":
        return None
    if family in _GPU_TIERS:
        # Every GeForce RTX number is d0[5-9]0 (3050..3090, 4060..4090, 5050..5090); anything
        # else ("RTX 6000 Ada", "RTX 4500 Ada", "RTX 5880 Ada") is an Nvidia workstation card.
        if family == "rtx" and not re.fullmatch(r"\d0[5-9]0", digits[:4]):
            return None
        gen = int(digits[:4]) // 1000
        table = _GPU_TIERS[family]
        if gen in table:
            return table[gen]
        return "current" if gen > max(table) else None
    if family == "arc":
        return "current-1" if rest.startswith("a") else "current"
    if family == "ryzen":
        if len(digits) >= 5:
            return "current"
        return _RYZEN_TIERS.get(int(digits) // 1000)
    if family == "ultra":
        series = int(digits) // 100
        return "current" if series >= 2 else None
    if family == "core":
        if len(digits) < 5:
            return None
        gen = int(digits[:2])
        if gen in _CORE_TIERS:
            return _CORE_TIERS[gen]
        return "current" if gen > max(_CORE_TIERS) else None
    return None


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
    aliases = "|".join(dict.fromkeys([normalise(base), key]))
    return f'{category},{brand_for(key)},{model},{spec},{tier},"{aliases}"'
