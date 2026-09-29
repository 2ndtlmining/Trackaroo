"""How a scraper tells run_daily what happened (#7, #11, R2, R3).

A scraper runs as a subprocess, so run_daily sees little more than its exit
code. Until 29-Sep-2026 every outcome -- a clean scrape, one that matched
nothing, a PCCG circuit-breaker trip, a cooldown skip -- exited 0, so a scrape
that matched nothing was logged "OK" and never alerted (#7). These codes keep
the four cases apart.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_DEGRADED = 2   # ran, but a category came back empty or the circuit breaker tripped
EXIT_SKIPPED = 3    # deliberately skipped (PCCG cooldown) -- expected, warns but never pages
EXIT_AUTH = 4       # the retailer rejected our credentials (PCCG Algolia 401/403) -- needs a human
