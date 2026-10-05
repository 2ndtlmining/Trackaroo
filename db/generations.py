"""Product generations: the one ordered list of series per product line (#17).

db/generations.toml lists each line's series newest first. A series'
position is its tier (0 current, 1 current-1, 2 current-2); position 3 or
later is out of scope unless the line sets keep_all. db/watchlist.py derives
every row's tier and tracked flag from here, seed.py mirrors it into the
`generations` table the dashboard reads labels from, and discover_rules.py
uses the `chips` tokens to place untracked parts.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import GENERATIONS_PATH

TIERS = ("current", "current-1", "current-2")
KNOWN_LINES = ("amd-cpu", "intel-cpu", "nvidia-gpu", "amd-gpu", "intel-gpu")
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_CHIP_RE = re.compile(r"^[a-z]+:[a-z0-9]+$")


class GenerationsError(ValueError):
    """db/generations.toml is unusable. The message names the line/series to fix."""


@dataclass(frozen=True)
class Series:
    key: str
    label: str
    line_id: str
    position: int
    chips: Tuple[str, ...]


@dataclass(frozen=True)
class Line:
    id: str
    keep_all: bool
    series: Tuple[Series, ...]


@dataclass(frozen=True)
class Generations:
    lines: Dict[str, Line]
    series: Dict[str, Series]

    def in_scope(self, key: str) -> bool:
        s = self.series[key]
        return s.position < len(TIERS) or self.lines[s.line_id].keep_all

    def tier(self, key: str) -> Optional[str]:
        s = self.series[key]
        if s.position < len(TIERS):
            return TIERS[s.position]
        return TIERS[-1] if self.lines[s.line_id].keep_all else None

    def chip_series(self, family: str, gen: str) -> Optional[Series]:
        token = f"{family}:{gen}"
        for s in self.series.values():
            if token in s.chips:
                return s
        return None

    def chip_gens(self, family: str) -> List[str]:
        prefix = f"{family}:"
        return [c[len(prefix):] for s in self.series.values() for c in s.chips if c.startswith(prefix)]


def line_id(brand: str, category: str) -> str:
    return f"{brand.strip().lower()}-{category.strip().lower()}"


def parse_generations(text: str, source: str = "generations.toml") -> Generations:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise GenerationsError(f"{source}: not valid TOML: {e}") from e

    raw_lines = data.get("line")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise GenerationsError(f"{source}: no [[line]] blocks")

    lines: Dict[str, Line] = {}
    series: Dict[str, Series] = {}
    chip_owner: Dict[str, str] = {}
    for raw in raw_lines:
        lid = raw.get("id")
        if lid not in KNOWN_LINES:
            raise GenerationsError(f"{source}: unknown line id {lid!r}; expected one of {KNOWN_LINES}")
        if lid in lines:
            raise GenerationsError(f"{source}: duplicate line {lid!r}")
        keep_all = raw.get("keep_all", False)
        if not isinstance(keep_all, bool):
            raise GenerationsError(f"{source}: line {lid}: keep_all must be true or false")
        entries = raw.get("series")
        if not isinstance(entries, list) or not entries:
            raise GenerationsError(f"{source}: line {lid} has no series")

        built: List[Series] = []
        for position, entry in enumerate(entries):
            key = entry.get("key") if isinstance(entry, dict) else None
            if not isinstance(key, str) or not _KEY_RE.match(key):
                raise GenerationsError(
                    f"{source}: line {lid}: series key {key!r} must be lowercase letters, digits and '-'"
                )
            if key in series:
                raise GenerationsError(f"{source}: duplicate series key {key!r}")
            label = entry.get("label")
            if not isinstance(label, str) or not label.strip():
                raise GenerationsError(f"{source}: series {key}: label is empty")
            chips = entry.get("chips", [])
            if not isinstance(chips, list) or not all(isinstance(c, str) and _CHIP_RE.match(c) for c in chips):
                raise GenerationsError(f"{source}: series {key}: each chip must look like 'family:gen', e.g. 'ryzen:9'")
            for chip in chips:
                if chip in chip_owner:
                    raise GenerationsError(f"{source}: chip {chip} is listed under both {chip_owner[chip]} and {key}")
                chip_owner[chip] = key
            s = Series(key=key, label=label.strip(), line_id=lid, position=position, chips=tuple(chips))
            built.append(s)
            series[key] = s
        lines[lid] = Line(id=lid, keep_all=keep_all, series=tuple(built))

    return Generations(lines=lines, series=series)


def load_generations(path=GENERATIONS_PATH) -> Generations:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise GenerationsError(f"{p}: file not found") from e
    return parse_generations(text, str(p))


@lru_cache(maxsize=1)
def default_generations() -> Generations:
    return load_generations()
