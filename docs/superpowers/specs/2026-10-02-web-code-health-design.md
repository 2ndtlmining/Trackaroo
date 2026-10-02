# Web code health: design

**Date:** 2026-10-02 · **Issue:** #30 · **Sub-project 1 of 6** in the look-and-feel / features backlog
**Status:** approved in conversation 2-Oct-2026, awaiting written-spec review

## 1. Purpose

This is a behind-the-scenes tidy-up of the SvelteKit dashboard's server code. It makes the next sub-projects cheaper and safer: catalogue filters (#23), compare (#26), charts (#27), buying signals (#31/#32) and the visual refresh (#22). All of those touch `web/src/lib/server/repos.ts`, which is 1,416 lines and holds every query.

### Success criteria
- Every page renders **the same HTML from the same data** as before. The one intended exception is the "how old is this data" wording (§6.5).
- The four suites stay green: pytest, svelte-check 0/0, vitest, Playwright.
- No source file under `web/src/lib/server/` is over ~350 lines. No client file (`.svelte`, or `src/lib/**` outside `server/`) imports from `$lib/server`.
- Page timings are the same or faster, measured before and after.

## 2. Data safety (owner requirement: "do not break our data")

This work only changes **how the website reads** data. Hard rules:

- **No changes** to `db/schema.sql`, `migrate.py`, the Python pipeline, the scrapers, `data/` (JSON snapshots and catalogues), backups, Docker or deploy files.
- **No new writes.** The write paths stay byte-for-byte equivalent in behaviour: price alerts (`upsertAlert`, `deleteAlert`) and `/discover` actions. They may move file, but their SQL is unchanged.
- **Query equivalence is proven, not assumed.** Before an old query is replaced by its refactored version, a test runs **both** against the same DB and asserts identical results:
  - the seeded test DB in CI;
  - locally, a **read-only** copy of `db/trackaroo.db`, opened `?mode=ro` from a temp copy, never the original path.
- **Golden-HTML safety net:** before any code moves, the rendered HTML of each main page is captured against the seeded e2e DB. After each step it must match.
- Nothing is deployed by this sub-project until its PR is merged and the owner runs `deploy/redeploy.sh`. Because nothing writes, rolling back is just redeploying the previous commit.

## 3. Out of scope
- Any visible feature or design change (those are sub-projects 2-6).
- Python code.
- Changing what any query returns, apart from deleting dead functions.

## 4. Already done (no work)
- Retailer-label dedupe.
- `SegmentedControl` and `PageHead`.
- Token contrast test.
- `/movers` change-label test.

## 5. Approach

`repos.ts` is split into focused modules under `src/lib/server/queries/`. **`repos.ts` stays as a short barrel that re-exports them**, so the 35 importing files keep working unchanged. Rewriting every import and deleting `repos.ts` was rejected: same result, much bigger and riskier diff.

## 6. Design

### 6.1 Safety net first
- **Golden HTML.** A vitest suite renders the loaders and pages to HTML against the seeded test DB and compares them with committed snapshots. Pages: home, `/products?category=gpu`, `/products?category=cpu`, one product page, `/deals`, `/movers`, `/compare` with two ids, `/discover`. Snapshot generation must be deterministic: fixed "today", no timestamps. If server-rendering pages under vitest proves impractical, snapshot the **loader data** (JSON) of each route instead. That pins every value the page shows, which is what a query refactor can break.
- **Query equivalence harness.** A small test helper runs an old and a new function against a DB and deep-compares their output. It is used for every query whose SQL changes (§6.3).

### 6.2 Delete dead code (with its tests)
- `LatestListingTable.svelte` and `StatTile.svelte`.
- `getBrands`, `getProductSparklines`, `freshnessLabel`.
- The `retailer`/`brand`/`tier`/`query`/`sort` filters of `getLatestListings` that no route passes, and the `groupListingsByProduct` sort.
- The `ProductGroup.sparkline` and `.deal` fields.

Each deletion is preceded by a grep proving no non-test caller.

### 6.3 One SQL fragment for "daily cheapest in stock"
- `dailyCheapestInStock(windowDays, { productScoped })` returns the SQL for "per-day cheapest in-stock price over the trailing window". It replaces the five hand-written copies:
  - `getProductStats`
  - `getProductDealStats`
  - `getCheapestPerModel`
  - `getDealCandidates`
  - the price-band/history copy
- It also keeps the bundle exclusions exactly as each copy has them today. If two copies differ, the difference is recorded and preserved via parameters; it is never silently unified.
- The two near-identical cheapest-listing queries share one builder.
- Every rewritten function goes through the equivalence harness (§6.1).

### 6.4 Split `repos.ts`
| Module | Contents (current names) |
|---|---|
| `queries/catalog.ts` | getTrackedProducts, getLaunchDates, getProductIndex, getCategoryCounts, getAvailableCounts, getLatestListings, groupListingsByProduct, getSparklines |
| `queries/history.ts` | getProductHistory, getPriceBand, getRetailerLatest |
| `queries/stats.ts` | getProductStats, getProductDealStats, getHeaderStats, plus the §6.3 fragment |
| `queries/deals.ts` | getCheapestPerModel, getDealCandidates |
| `queries/movers.ts` | getMovers, getProductMoves |
| `queries/compare.ts` | getComparisonData |
| `queries/alerts.ts` | AlertRow, upsertAlert, deleteAlert, getProductAlerts |
| `queries/health.ts` | tableExists, getRetailerFreshness |
| `repos.ts` | `export * from './queries/...'`, nothing else |

The exact grouping may shift where a function is tightly coupled to another, but the 350-line limit and "one concern per file" hold.

### 6.5 Types and one rule for "how old"
- DTO interfaces move to `src/lib/models.ts`. Client components import types from there. A vitest guard fails if any client file imports `$lib/server`.
- "How old":
  - `daysBehindToday(date)` plus `stalenessLabel(date)` for date-only fields (snapshot dates);
  - `formatRelative(timestamp)` only for true timestamps (`scraped_at`, run times).
- The product-page "Updated …" stamp and the stale banner then describe the same date the same way. This is the one intended HTML change; its golden snapshots are updated in a dedicated, reviewed commit.

## 7. Error handling
No behaviour change. The loaders keep their current 404 and error paths, pinned by the existing tests plus the golden snapshots.

## 8. Testing
- New: golden HTML or loader-data snapshots (§6.1), the query equivalence tests (§6.3), the client-import guard (§6.5), and `stalenessLabel`/`daysBehindToday` unit tests.
- Existing: all four suites green after **every** task, not only at the end.
- Read-only equivalence run against a temp copy of the real local DB, recorded in the PR.
- Before/after timings with `web/scripts/measure.sh`, recorded in the PR.

## 9. Deploy
Merge, then `deploy/redeploy.sh` outside 04:00-09:59 Melbourne. No migration runs and nothing in `db/` or `data/` changes.
