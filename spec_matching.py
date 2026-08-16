"""
Pure name-matching helpers for spec sync (no I/O, no DB access).

Matches canonical watchlist/product names against external spec-source
record names. Deliberately conservative: anything that is not a confident
match returns None and is left unmatched (reported, never guessed).

Conventions:
- GPU records are dicts with at least a "name" key; VRAM-variant records
  carry VRAM in GB (float) under "vram_gb" (normalized records from
  sync_specs.parse_gpu_records) or "memorySize" (raw dataset records).
- CPU records are dicts with at least a "name" key.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_BRAND_TOKENS = ("amd", "intel", "nvidia")


def normalize_name(name: str) -> str:
    """Normalize a product name for comparison.

    Lowercases, replaces every non-alphanumeric run with a single space,
    and collapses whitespace. 'GeForce RTX 4070 Ti SUPER' and
    'geforce rtx 4070 ti super' both become 'geforce rtx 4070 ti super'.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", name.lower())).strip()


def strip_brand(normalized_name: str) -> str:
    """Drop a leading brand token ('amd', 'intel', 'nvidia') if present.

    Expects an already-normalized name. 'amd ryzen 9 9950x3d' becomes
    'ryzen 9 9950x3d'; 'ryzen 9 9950x3d' is unchanged.
    """
    parts = normalized_name.split(" ")
    if parts and parts[0] in _BRAND_TOKENS:
        return " ".join(parts[1:]).strip()
    return normalized_name


def _same_value(a: Any, b: Any) -> bool:
    """Tolerant numeric equality for values that may be int/float/None."""
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return False


def _record_vram(r: Dict[str, Any]) -> Any:
    """VRAM (GB) of a record, whatever its shape: normalized records carry
    'vram_gb', raw dataset records carry 'memorySize'."""
    if "vram_gb" in r:
        return r["vram_gb"]
    return r.get("memorySize")


def match_gpu(
    model: str,
    vram_gb: Optional[float],
    records: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Match a watchlist GPU model to a spec-dataset record.

    Strategy, in order:
    1. Exact match on normalized name.
    2. Prefix match where the dataset name's extra tail is exactly
       '<digits> gb' (VRAM-variant naming). If the watchlist carries a
       vram_gb, candidates whose memorySize does not equal it are
       dropped. A single remaining candidate wins; otherwise no match.

    Returns the matched record, or None when no confident match exists.
    """
    n = normalize_name(model)
    by_norm: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        by_norm.setdefault(normalize_name(r["name"]), []).append(r)

    if n in by_norm:
        cands = by_norm[n]
        if len(cands) == 1:
            return cands[0]
        if vram_gb is not None:
            cands = [r for r in cands if _same_value(_record_vram(r), vram_gb)]
        return cands[0] if len(cands) == 1 else None

    cands: List[Dict[str, Any]] = []
    for key, recs in by_norm.items():
        if key.startswith(n) and re.fullmatch(r"\d+ gb", key[len(n):].strip()):
            cands.extend(recs)
    if not cands:
        return None
    if vram_gb is not None:
        cands = [r for r in cands if _same_value(_record_vram(r), vram_gb)]
    return cands[0] if len(cands) == 1 else None


def match_cpu(model: str, records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Match a watchlist CPU model to a source record.

    Strategy, in order:
    1. Exact match on normalized name (covers Intel CSV 'Product' names,
       which line up with the watchlist model verbatim).
    2. Exact match after stripping a leading brand token from both sides
       (covers AMD.com page names like 'AMD Ryzen 9 9950X3D').

    Returns the matched record, or None when no confident match exists.
    """
    n = normalize_name(model)
    for r in records:
        if normalize_name(r["name"]) == n:
            return r

    n_stripped = strip_brand(n)
    for r in records:
        if strip_brand(normalize_name(r["name"])) == n_stripped:
            return r
    return None
