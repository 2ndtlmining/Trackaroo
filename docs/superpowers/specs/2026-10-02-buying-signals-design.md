# Buying signals: design

**Date:** 2026-10-02 · **Issues:** #32 (MSRP vs today's AUD price), #31 (the rest of "good time to buy") · **Sub-project 3 of 6**
**Status:** approved in conversation 2-Oct-2026, awaiting written-spec review

## 1. Purpose

Help the owner answer "is this a good price, and is now a good time to buy?" on every product:
- an honest comparison with the launch MSRP in today's Australian dollars;
- a set of separate, explainable signals, not a single score. This is consistent with the 17-Aug "deal score declined" decision.

### Owner decisions (2-Oct-2026)
- MSRP is converted at **today's** exchange rate.
- **No emojis anywhere in the UI.** Use icons.

### Success criteria
- The product headline shows "N% under/over US launch MSRP (≈A$X inc. GST)". The conversion (rate, source, date, GST) is explained on hover/focus.
- The catalogue has a sortable "vs MSRP" column, and /deals can filter to "below MSRP".
- No unlabelled USD amount remains in the UI.
- The product page shows the signal checklist with an icon per badge. Each badge states its evidence window. Products under the history gate show "Gathering history (N days)".
- The price chart shows AU sale events as dashed vertical markers with labels, with no new hue.
- The four suites are green, the axe checks stay green, and a test forbids emoji in web sources.
- New runtime dependency: `@lucide/svelte` (MIT). It is the only one.

## 2. Data safety
- **One additive table**, `fx_rates`, created by `migrate.py` (and `db/schema.sql`) on startup like previous bookkeeping tables. No change to price tables, scraping, snapshots or backups.
- **One outbound request per day** to fetch the exchange rate. It is a `run_daily.best_effort` step, so a failure can never break the run. It is mocked in all tests (conftest blocks real network).
- The web only **reads** the cached rate; there is never a fetch at request time.

## 3. Out of scope
- A curated AU RRP (#32 option b).
- "Launch street price" (#32 option c).
- A composite verdict.
- Price-to-performance (sub-project 6).

## 4. Exchange rate

**Table:**
```sql
CREATE TABLE fx_rates (
    rate_date    TEXT PRIMARY KEY,   -- YYYY-MM-DD, the source's date for the rate
    aud_per_usd  REAL NOT NULL CHECK (aud_per_usd > 0),
    source       TEXT NOT NULL,      -- 'rba' | 'frankfurter'
    fetched_at   TEXT NOT NULL
);
```

**Fetcher** (`fx.py`, a best-effort step in `run_daily.py`, after ingest):
- **Primary source:** the RBA F11.1 daily exchange rates CSV (`https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv`). It gives USD per AUD (`FXRUSD`); store `aud_per_usd = 1 / value`.
- **Fallback:** if the RBA fetch or parse fails, use Frankfurter (`https://api.frankfurter.app/latest?from=USD&to=AUD`), the ECB reference rate.
- Upsert the latest rate, plus any recent days that are missing.
- Sanity bounds: reject rates outside 1.0–2.5 AUD per USD and log a WARNING.
- Timeout of a few seconds, plus a polite User-Agent.
- Logs never include anything secret (there is nothing secret here).

**Health:** `check_fx_rate` gives a WARNING if the newest rate is older than 7 days. It is never an ERROR.

## 5. MSRP comparison (#32)
- **Formula:** `msrpAud = launch_msrp_usd × aud_per_usd × 1.10`, using the latest `fx_rates` row.
- **Delta:** `(shownPrice − msrpAud) / msrpAud`. Rounded to whole percent for display, kept unrounded for sorting.
- **Where it appears:**
  - **Product headline:** "3% under US launch MSRP (≈A$1,745 inc. GST)". A tooltip/`<details>` reads: "US$1,099 × 1.5432 AUD/USD (RBA, 1 Oct 2026) + 10% GST".
  - **Catalogue:** a sortable `vs MSRP` column. A new `sort=msrp` key, default direction asc (most under MSRP first); nulls last. It uses `shownPrice`, so a retailer view compares that retailer's price.
  - **/deals:** a "Below MSRP" toggle (`?below_msrp=1`).
- **Labelling:** every USD amount reads "US$1,099" via one formatter (the existing `formatUsd`, verified everywhere). `SpecPanel` and compare already say "US launch MSRP".
- **Missing data:** no MSRP, no rate or no current price gives "–", and the row sorts last.

## 6. Signals checklist (#31)
Pure functions live in `web/src/lib/buySignals.ts`, which already has `dailyLows`, `lowSummary` and `windowStats`.

| Signal | Rule | Badge text (example) | Icon |
|---|---|---|---|
| Percentile | Share of days in the window (up to 180) whose daily low is **higher** than today's price | "Cheaper than 82% of days (last 120 days)" | check (good ≥ 70%), dash otherwise |
| Lowest in N days | Days since a lower daily low; "lowest since tracking began" if none | "Lowest in 94 days" | check (≥ 30 days), dash otherwise |
| vs 30-day avg | Existing avg30 | "3.1% below its 30-day average" | check if ≥ 2% below; dash within ±2%; alert if ≥ 2% above |
| 7-day trend | Last 7 daily lows: (last − first) / first | "7-day trend: falling (−4%)" | trending-down / dash (within ±1%) / trending-up |
| Sale event | The next AU sale event starting within 21 days, or one running now | "Click Frenzy starts in 12 days" / "Black Friday sale on now" | calendar |
| Successor | A manual flag on the product's series | "Successor announced (RTX 60)" | alert |

- **History gate:** fewer than `MIN_HISTORY_POINTS` daily lows gives a single "Gathering history (N days)" badge, replacing the history-based badges.
- **Evidence:** every badge states its window or evidence in the visible text or a focusable tooltip. The icon is decorative (`aria-hidden`) and the text carries the meaning, so the badge never relies on colour or the icon alone.
- **Stats strip:** 30 / 90 / 180-day low · median · high. The 180-day column is added next to the existing 30/90-day strip.

## 7. Sale events
`web/src/lib/saleEvents.ts` exports `saleEventsFor(year): SaleEvent[]` and `upcomingSaleEvent(today, horizonDays)`.
- **Rule-based events, computed:**
  - EOFY sales: 15–30 June.
  - Singles Day: 11 November.
  - Black Friday: the day after US Thanksgiving (the 4th Thursday of November), through Cyber Monday.
  - Boxing Day: 26–31 December.
- **Variable events, curated per year in the same file:**
  - Click Frenzy "Main Event" (November).
  - Amazon Prime Day (July).
  - Each needs a dated entry per year. A unit test fails when the **next** calendar year has no curated entry, so the owner is reminded each year.
- **Chart:** `PriceChart` draws events overlapping the plotted range as dashed vertical lines with a small label. It uses the existing muted text token, with no new hue.

## 8. Successor flag
`web/src/lib/successors.ts` is a static map from series name to successor label, e.g. `{ 'RTX 50': 'RTX 60' }`. It starts empty, and the owner adds entries in a PR when a successor is announced. The README explains how.

## 9. Icons, look, and no emojis
**Icon set:** **Lucide** via `@lucide/svelte`.
- MIT licence, tree-shaken (only the imported icons ship), and consistent 24px line icons with a configurable stroke.
- The owner already uses Lucide in other Svelte projects (the Brewery app uses `lucide-svelte`). `@lucide/svelte` is the current Svelte 5 package of the same icon set.
- game-icons.net was considered and not used. Its illustrative style suits games, not a price dashboard, and its CC BY 3.0 licence needs a visible attribution.
- Icons used: `CircleCheck`, `Minus`, `TrendingDown`, `TrendingUp`, `CalendarClock`, `TriangleAlert`, `Info`, and `BadgeDollarSign` for the MSRP line.
- Every icon is `aria-hidden="true"`, and the text next to it carries the meaning.
- The existing hand-drawn inline SVGs (header, theme toggle, sparkline) stay as they are; there is no churn for its own sake.

**Look (owner: "make it look as good as you can"):**
- **Badges.** Each signal is a pill-shaped chip: an icon inside a small tinted circle, then a bold short claim ("Lowest in 94 days"), then muted evidence text ("last 120 days").
- **Colour by tone, using existing semantic tokens only:**
  - `success` for good signals;
  - `warning` for heads-ups (sale soon, successor announced);
  - neutral `text-muted` for "flat" or "no signal";
  - nothing red unless a price is clearly above average.
- **Layout.**
  - Chips wrap in a two-column grid on desktop and stack on phones.
  - The panel title "Is now a good time to buy?" sits above them.
  - The stats strip below is a compact 3×3 table (30 / 90 / 180 days × low / median / high) with tabular numerals.
- **MSRP line.** Directly under the headline price: `BadgeDollarSign` icon, then "3% under US launch MSRP", then a muted "≈A$1,745 inc. GST" with an `Info` button that opens the conversion explanation (keyboard-focusable popover or `<details>`).
- **Catalogue "vs MSRP" column.** A short signed percentage ("−3%" / "+12%") in tabular numerals, tinted by tone, with "–" when unknown.
- **Implementation guidance.** UI tasks load the `frontend-design` skill for the visual pass. Every new colour use must pass the existing `contrast.test.ts` and the axe checks in both themes.

**No emojis:** `web/test/noEmoji.test.ts` scans `web/src/**/*.{svelte,ts}` and fails on any emoji code point (Unicode Extended_Pictographic). This enforces the owner rule.

## 10. Testing
- **pytest:**
  - RBA CSV parsing (fixture file), with the inversion to AUD per USD;
  - fallback to Frankfurter when the RBA fails;
  - out-of-bounds rejection;
  - upsert idempotence;
  - the migration creates `fx_rates`;
  - `check_fx_rate` is WARNING-only;
  - the run_daily step is best-effort.
- **vitest:**
  - the MSRP formula and delta (including missing data);
  - each signal rule at its thresholds;
  - the history gate;
  - sale-event dates (Thanksgiving computation for several years, curated-year guard);
  - `upcomingSaleEvent` boundaries;
  - the `sort=msrp` order;
  - the no-emoji guard.
- **Playwright:**
  - the product page badges render with icons and the evidence text;
  - "vs MSRP" in the headline with its explanation;
  - the catalogue `vs MSRP` column sorts;
  - the /deals "Below MSRP" filter;
  - chart sale markers present when an event falls in range;
  - axe stays green in both themes.

## 11. Deploy
Merge, then `deploy/redeploy.sh` outside 04:00-09:59 Melbourne. The migration adds `fx_rates` automatically. The first rate is fetched on the next daily run, or immediately via `docker compose exec trackaroo python fx.py`. Until a rate exists, MSRP comparisons show "–".
