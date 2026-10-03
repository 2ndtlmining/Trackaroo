# Price-to-performance: design

**Date:** 2026-10-03 · **Issue:** #33 · **Sub-project 6 of 6**
**Status:** approved in conversation on 3-Oct-2026; awaiting written-spec review.

## 1. Purpose
Answer "which part gives the most performance per Australian dollar today?" for GPUs and CPUs, using clearly labelled, sourced metrics and never one blended score.

### Owner decisions (3-Oct-2026)
- **Supersede the 17-Aug "no value score" decision**, but only for this transparent form:
  - separate labelled metrics (GPU raster 1440p, GPU ray tracing 1440p, CPU gaming 1080p), each with its source and date;
  - the Pareto frontier and best-per-budget as explainable signals.
- **The performance index is researched by Claude from fetched, published sources** and spot-checked by the owner.
  - Nothing comes from memory.
  - A product the source table doesn't contain is left out and listed. It is never estimated.
- **Scope:**
  - the index;
  - $/perf columns on /products and /compare;
  - the `/value` scatter with the Pareto frontier;
  - best per budget.

  Head-to-head matchups are a follow-up issue.

### Success criteria
- Every tracked `current` and `current-1` product (70 today) has an entry for its category's metrics, or appears on the documented "not in source" list in the PR.
- Every value on screen states its metric and source on hover or focus.
- `/value` shows the scatter, the frontier and the budget winners, with a table equivalent for screen readers.
- The four test suites are green, axe stays green in both themes, and mobile has no overflow.

## 2. Data
- **File.** `db/perf_index.json` is bundled into the web build with a static import, the same way the changelog is. It is not stored in the DB: there is no table, no pipeline step and no migration. Updates go through a PR plus a redeploy.
- **Shape:**
```json
{
  "metrics": {
    "gpu_raster_1440p": { "label": "1440p raster", "unit": "relative %", "source": "TechPowerUp, <review title>", "source_url": "https://…", "as_of": "2026-09", "baseline": "<card at 100%>" },
    "gpu_rt_1440p":     { "label": "1440p ray tracing", "unit": "relative %", "source": "…", "source_url": "…", "as_of": "…", "baseline": "…" },
    "cpu_gaming_1080p": { "label": "1080p gaming", "unit": "relative %", "source": "…", "source_url": "…", "as_of": "…", "baseline": "…" }
  },
  "products": {
    "GeForce RTX 5070 Ti 16GB": { "gpu_raster_1440p": 100, "gpu_rt_1440p": 100 },
    "Ryzen 7 9800X3D": { "cpu_gaming_1080p": 100 }
  },
  "not_in_source": { "gpu_rt_1440p": ["GeForce RTX 3050 6GB"] }
}
```
- **Keys.**
  - GPUs: `"<watchlist model> <spec>"`, for example `GeForce RTX 3050 8GB`, matching the watchlist `spec` column (the VRAM).
  - CPUs: the watchlist `model`.

  The web resolves a product with the same rule, using `products.model` plus `vram_gb`.
- **One source table per metric.** Every value of a metric comes from a single chart, so all values share one baseline and are comparable. Relative percentages are stored as published.
- **Value units.** "Perf per A$1,000" is `metric / price × 1000`. "A$ per perf point" is `price / metric`.
- **Test.** `unit_testing/test_perf_index.py`:
  - every tracked `current` and `current-1` product has its category's metrics, or is listed under `not_in_source`;
  - `current-2` gaps are allowed and reported as a pytest warning;
  - every metric has a source, a source_url and an as_of;
  - values are positive numbers.

## 3. Logic (pure, `web/src/lib/value.ts`)
- **`perfFor(product, metric)`:** returns a number or null.
- **`perfPerKilo(price, perf)`** and **`audPerPoint(price, perf)`:** return null when either input is null or not positive.
- **`paretoFrontier(points)`:** points are `{ id, price, perf }`. It returns the ids not dominated by any other point, where another point dominates when it has price ≤ and perf ≥, with at least one of the two strict. Ties are kept. The result is sorted by price ascending.
- **`bestPerBudget(points, brackets, opts)`:**
  - for each bracket max (400, 700, 1000, 1500, 2500 AUD), among points with price ≤ max, pick the highest perf;
  - a tie on perf goes to the lower price;
  - the runner-up is the next best;
  - the gap is `(winner.perf − runnerUp.perf) / runnerUp.perf`;
  - `opts.exclude8gb` drops GPUs whose VRAM is 8 GB or less.
- **Prices** are the shown price: the cheapest in-stock price today, the same as the deals and MSRP rule (active, non-bundle, global latest date). Products with no in-stock price are excluded from /value, and the panel says how many were excluded.

## 4. UI
- **Columns.** On /products (xl and up) and /compare, add "perf / A$1k" (per category metric: raster for GPUs, gaming for CPUs) as a whole number in tabular numerals. Its hover and focus text reads "1440p raster per A$1,000. TechPowerUp, <title>, Sep 2026". A product with no data shows "–" and sorts last. Add the sort key `sort=value` (descending by default).
- **`/value` page.** Add it to the nav as "Value". It has a PageHeader, a GPU/CPU SegmentedControl and a metric SegmentedControl (raster or RT for GPUs).
  - **Scatter:** an SVG chart with price (AUD) on x and the metric on y. The axes are labelled with units. Frontier points use the accent colour and are joined by a step line; the rest are muted.
  - **Point details:** each point is focusable and shows a tooltip with model, price, metric value and perf per A$1k.
  - **Fallback:** a visually hidden table with the same rows.
  - **Source:** a source line under the chart.
- **Best per budget.** One card per bracket showing the winner (name, price, perf, perf per A$1k), the runner-up and the gap ("12% faster than the runner-up"). An "Exclude 8 GB cards" toggle applies to GPUs only. An empty bracket says "Nothing in stock under $400".
- **Design.** Use the existing tokens, Lucide icons and no emojis, and load the dataviz skill for the chart.

## 5. Decision log
A `docs/ARCHITECTURE.md` entry: "Price-to-performance: separate sourced metrics and Pareto frontier; supersedes the 17-Aug 'no value score' note for this transparent form only."

## 6. Out of scope
- Head-to-head matchups (follow-up issue).
- PassMark, UserBenchmark and TFLOPS headlines.
- Any blended score.
- Productivity metrics.

## 7. Deploy
There are no data, schema or pipeline changes. Merge, then run `deploy/redeploy.sh` outside 04:00–09:59. Add a CHANGELOG line under Unreleased.
