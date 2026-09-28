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
    ("rtx", re.compile(
        r"\brtx ?(\d{4})(?!\d)(?: ?(ti)(?![a-z]))?(?: ?(super)(?![a-z]))?(?![a-z0-9])")),
    ("rx", re.compile(
        r"\b(?:rx|radeon) ?(\d{4})(?!\d)"
        # PowerColor puts its product line between the number and the
        # suffix ("RX 9070 Reaper GRE"), so skip at most one word that
        # is not itself the suffix before looking for it.
        r"(?:\s+(?!(?:xtx|xt|gre)(?![a-z]))[a-z]+)?"
        r"(?: ?(xtx|xt|gre)(?![a-z]))?(?![a-z0-9])")),
    ("arc", re.compile(r"\barc ?([ab]\d{3})(?!\d)(?![a-z0-9])")),
)
_CPU_PATTERNS = (
    ("ryzen", re.compile(
        r"\b(?:ryzen ?[3579]|r[3579])(?: pro)? ?(\d{4,5})"
        r"(?: ?(x3d\d?|xt|x|gt|ge|g|f)(?![a-z0-9]))?(?![a-z])(?![0-9])")),
    ("ultra", re.compile(
        r"\bultra ?[3579](?: processor)? ?(\d{3})(?!\d)(ks|kf|k|f|t)?(?![a-z])(?: ?(plus)(?![a-z]))?")),
    ("core", re.compile(r"\bi[3579] ?(?:processor )?(\d{4,5})(?!\d)(ks|kf|k|f|t)?(?![a-z])")),
)
# Asus glues its "overclocked" prefix straight onto the VRAM digits
# ("O8G", "O16G"), so the leading "o" is optional here rather than part of
# the exclusion the plain \b boundary would otherwise impose.
_VRAM = re.compile(r"\bo?(\d{1,2}) ?gb?(?![a-z0-9])")
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
