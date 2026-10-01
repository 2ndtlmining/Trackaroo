"""How a scraper tells run_daily what happened (#7, #11, R2, R3).

A scraper runs as a subprocess, so run_daily sees little more than its exit
code. Until 29-Sep-2026 every outcome -- a clean scrape, one that matched
nothing, a PCCG circuit-breaker trip, a cooldown skip -- exited 0, so a scrape
that matched nothing was logged "OK" and never alerted (#7). These codes keep
the four cases apart.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

EXIT_OK = 0
EXIT_DEGRADED = 2   # ran, but a category came back empty or the circuit breaker tripped
EXIT_SKIPPED = 3    # deliberately skipped (PCCG cooldown) -- expected, warns but never pages
EXIT_AUTH = 4       # the retailer rejected our credentials (PCCG Algolia 401/403) -- needs a human

LOGGER = logging.getLogger(__name__)

# run_daily passes a temp path here; the scraper writes its counts to it after
# every category, so they survive run_daily's timeout kill (R2, R3). Unset
# (a scraper run by hand) makes every flush a no-op.
REPORT_ENV = "TRACKAROO_RUN_REPORT"

# Per-category counters. matched is set in Task 5; the page and card counters
# are filled by the scrapers' telemetry (Task 7, #14).
COUNTERS = ("matched", "pages_attempted", "pages_fetched", "cards_seen", "cards_dropped")


class RunReport:
    """Per-run telemetry a scraper hands back to run_daily."""

    def __init__(self, retailer: str, path: Optional[Path] = None) -> None:
        self.retailer = retailer
        env = os.environ.get(REPORT_ENV)
        self.path = path if path is not None else (Path(env) if env else None)
        self.categories: Dict[str, Dict[str, int]] = {}
        self.notes: List[str] = []

    def category(self, name: str) -> Dict[str, int]:
        """The live counter dict for one category (created on first use)."""
        return self.categories.setdefault(name, {c: 0 for c in COUNTERS})

    def set(self, category: str, **counts: int) -> None:
        self.category(category).update(counts)

    def note(self, text: str) -> None:
        self.notes.append(text)

    @property
    def matched(self) -> int:
        return sum(c["matched"] for c in self.categories.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "retailer": self.retailer,
            "matched": self.matched,
            "categories": self.categories,
            "notes": self.notes,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def flush(self) -> None:
        """Write the report now (atomically). Never raises."""
        if self.path is None:
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self.to_dict()), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            LOGGER.warning("Could not write run report %s: %s", self.path, e)


def read_run_report(path: Path) -> Optional[Dict[str, Any]]:
    """The report a scraper left at ``path``, or None if it never wrote one."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def exit_code_for(report: RunReport, categories: Sequence[str] = ("cpu", "gpu")) -> int:
    """EXIT_OK when every category matched something, else EXIT_DEGRADED (#7)."""
    return EXIT_OK if all(report.category(c)["matched"] > 0 for c in categories) else EXIT_DEGRADED
