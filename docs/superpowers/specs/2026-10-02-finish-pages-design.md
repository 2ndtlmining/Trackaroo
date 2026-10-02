# Finish the pages: design

**Date:** 2026-10-02 · **Issues:** #23, #26, #27, #29 · **Sub-project 2 of 6** (look-and-feel / features backlog)
**Status:** approved in conversation 2-Oct-2026, awaiting written-spec review

## 1. Purpose

Make the dashboard useful for deciding what to buy:
- the GPU/CPU catalogue can be filtered and sorted, and the view lives in the URL;
- Compare shows the winner in each row;
- the price chart shows the 30-day average and where data is missing;
- the site passes automated accessibility checks and fails gracefully when the DB is unreadable.

### Owner decisions (2-Oct-2026)
- Catalogue filters: **max price**, **brand + generation**, **in stock + retailer**. VRAM and core-count filters are not wanted.
- One spec and one PR, implemented as separate tasks.

### Success criteria
- Every catalogue filter and sort is reflected in the URL and restored on reload or from a shared link.
- Compare marks the best value in every comparable numeric row.
- The chart shows the 30-day average line, gap connectors and the non-zero-axis note.
- Playwright accessibility checks (axe) pass on every main page in light and dark themes, with no `serious` or `critical` violations.
- A DB failure renders a styled error page with a retry link.
- Pages stay fast (catalogue under 20 ms warm TTFB) and work at 390 px.
- The four test suites are green.

## 2. Data safety
- Read-only feature work. No changes to `db/schema.sql`, `migrate.py`, Python, scrapers, `data/`, backups, Docker or deploy files.
- No new writes.
- One new read query is allowed: product-level 30-day sparklines. It uses the existing `dailyCheapestInStock` builder in `web/src/lib/server/queries/sql.ts`.
- Tests never open `db/trackaroo.db`.

## 3. Out of scope
- VRAM and core-count filters.
- A visual redesign (sub-project 5).
- New data sources.

## 4. Catalogue (#23)

**Route:** `/products?category=gpu|cpu` (the GPUs and CPUs nav entries).

### Filters
All filters live in the URL, are parsed in `web/src/lib/filters.ts`, and are applied in memory in the loader to the per-category product groups it already builds. There are about 60 products per category, so no new SQL is needed.

| Param | Values | Meaning |
|---|---|---|
| `max` | positive integer AUD | Hide products whose shown price is above it. Preset buttons $500 / $1,000 / $2,000 / Any, plus a number input. |
| `brand` | `NVIDIA` / `AMD` / `Intel` (repeatable or comma list) | Only those brands. |
| `gen` | `current` / `current-1` / `current-2` (repeatable) | Generation tier. Each tier is labelled with its series per category (e.g. "RTX 50", "Ryzen 9000"), derived from the products in the tier. |
| `in_stock` | `1` | Existing. Only products with an in-stock listing. |
| `retailer` | `scorptec` / `pccg` / `umart` | Only products listed at that retailer. Shown price and `max` use that retailer's cheapest (in-stock if `in_stock=1`) price. |
| `sort` | `price` / `name` / `spec` / `released` / `listings` | Sort key. `spec` is VRAM for GPUs and cores for CPUs. |
| `dir` | `asc` / `desc` | Sort direction. Each key has a natural default: price asc, name asc, spec desc, released desc, listings desc. |

- Invalid or unknown values are ignored: the parser drops them, so a bad link degrades to "no filter" and never errors.
- The existing `q` search and `compare` params keep working alongside the new ones.
- The existing "hide never-listed" toggle keeps working.
- A filter change updates the URL with `replaceState` semantics (no history spam) and works without JS as a GET form.

### Table
- **Sortable headers.** Each header is a link or button with `aria-sort` on the active column and a visible arrow.
- **Group headers.** When sorted by the default order, the existing grouping by series stays and each header gains the release year from launch dates (e.g. "NVIDIA · RTX 50 (Blackwell) · 2025"). Sorting by any other key flattens the list: groups would fight the sort.
- **30-day trend.** A small sparkline per product: the daily cheapest in-stock price over 30 days, from one new query (`getProductSparklines(db, category, 30)`) built on `dailyCheapestInStock`. This is a product-level replacement for the dead function removed in #30, with new tests. The sparkline has an accessible label, e.g. "30-day trend: down 4%".
- **CPU columns.** Socket and threads, from `specs.socket` and `specs.thread_count`, next to cores. Missing values show "–".

### Phone (390 px)
Filters collapse into a "Filters (N active)" button. It opens a panel (a native `<dialog>`) with the same controls and a "Show N results" button. No horizontal scrolling.

### Empty state
When no product matches: "No products match these filters." plus a "Clear filters" link.

## 5. Compare (#26)
`web/src/lib/compareRows.ts` gains a direction per numeric row:
- **Higher is better:** VRAM, memory bus, bandwidth, L2 cache, base clock, boost clock, cores/shaders, threads.
- **Lower is better:** current price, TDP, process (nm).
- **Neutral, no highlight:** launch MSRP, launch date, architecture, generation, memory type, bus interface, GPU die, codename, socket.

The best value in a row is bold with a small "Best" label, so colour is not the only signal. Ties mark every tied cell. Rows with fewer than two numeric values, or where all values are equal, are not marked. This is pure logic in `compareRows.ts`, unit-tested.

## 6. Price chart (#27) — `PriceChart.svelte`
- **30-day average:** a horizontal dashed line at the product's 30-day average (`ProductStats.avg30`, already loaded), labelled "30-day avg $X" in the legend. Hidden when avg30 is null.
- **Gaps:** where a series has missing days between points, the gap is drawn as a dotted segment, not a solid one. The data table (existing `<details>`) is unchanged.
- **Axis note:** when the y-axis minimum is above 0, a small caption: "Axis doesn't start at $0."
- The existing textContent tooltip, legend and accessible summary stay.

## 7. Accessibility and errors (#29)
- **Error page.** `+error.svelte` is restyled with the site tokens: a heading, the friendly message `hooks.server.ts` already produces ("Prices are temporarily unavailable — the database could not be opened" and similar), a "Try again" link to the same URL, and a link home. The status code shows in small text. SvelteKit's status is kept; `handleServerError` cannot change it, and no route is restructured for this.
- **Command palette (Ctrl+K)** gets the WAI-ARIA combobox pattern:
  - the input has `role="combobox"`, `aria-expanded`, `aria-controls` and `aria-activedescendant`;
  - the results have `role="listbox"` and `role="option"` with `aria-selected`;
  - Up/Down move, Enter opens, Escape closes and returns focus to the trigger, and Tab is trapped while open.
- **Automated checks.** `@axe-core/playwright` is added as a **dev dependency only**. A Playwright spec runs axe on `/`, `/products?category=gpu`, `/products?category=cpu`, a product page, `/deals`, `/movers`, `/compare` with two ids, `/discover` and a 404 page, in light and dark themes. It fails on `serious` or `critical` violations. Existing violations it finds are fixed in this sub-project; a rule may only be disabled with a written reason in the spec file.

## 8. Testing
- **vitest:**
  - filter/sort parsing and serialising round-trip, including invalid values;
  - in-memory filtering and sorting of product groups (each filter alone and combined, retailer price substitution, empty result);
  - compare "best" rules (directions, ties, single value);
  - `getProductSparklines` against the seeded DB;
  - chart helpers (gap detection, axis-starts-at-zero check).
- **Playwright:**
  - filter by each control and check the URL and rows;
  - sort toggling and `aria-sort`;
  - reload restores state;
  - the phone filter panel at 390 px;
  - Compare "Best" markers;
  - chart average line and axis note present;
  - palette keyboard flow;
  - the axe spec.
- **Gate:** pytest, svelte-check 0/0, vitest and Playwright all green. Catalogue warm TTFB measured before and after.

## 9. Deploy
Merge, then `deploy/redeploy.sh` outside 04:00-09:59 Melbourne. No migration, no data change.
