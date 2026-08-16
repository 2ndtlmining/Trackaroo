# Phase 3 — Frontend Build Plan (handoff doc)

Single-file plan so any model can build the Trackaroo frontend without re-deriving this session. Read `README.md`, `STATUS.md`, `SPEC.md`, `SCOPE_RULES.md`, `DECISIONS.md`, `db/schema.sql`, and `query.py` for full context; this file is the executable plan.

**Status (2026-08-14):** Backend complete, 226 tests green. Frontend not started. Plan finalized with user; decisions below are locked.

**Superseded (2026-08-15):** all of M0–M5 are done — the frontend is built, tested (117 vitest + 28 Playwright e2e) and shipped. This file is kept as the historical handoff record; see `STATUS.md` for the current state.

## Locked decisions

- **Stack:** SvelteKit + TypeScript + Tailwind v4 in `web/`, `adapter-node` (matches Proxmox/FluxTracker deploy later).
- **DB access:** read-only via better-sqlite3 from server routes. Open with `PRAGMA busy_timeout=5000`, **NEVER toggle journal mode** (WAL is set by Python writers; a mode change on read takes an exclusive lock → `database is locked` — see DECISIONS.md). `node:sqlite` is the documented fallback if the native build fails. No API layer, no ORM, no schema changes.
- **Charts:** uPlot (~8kb, zero default theme). Tooltip/crosshair hand-rolled and token-styled.
- **Chart series:** all price lines in the one accent hue; variants distinguished by line style (solid/dashed/dotted).
- **Deal signal (SPEC §9.4):** deferred — revisit once listings have real history depth.
- **Tests:** vitest for DB repositories + load functions (temp DB seeded from `data/*.json`) + a few component smoke tests.
- **Design:** dark mode default + full light mode; flat, no gradients/shadows/glassmorphism; **one** restrained accent (NOT purple/violet); 4–8px radii; color semantic only (green = price down, red = up, gray = no-change/stale) rendered as Railway-style dot+label chips; tabular-nums + mono font for every price/%/count/timestamp; sentence case, 2 weights max; borders+whitespace over shadows (Linear hairline table rows, Railway-style stat tiles); density over decoration.
- **Anti-scope:** no auth, no multi-user, no API layer, no new DB, no emoji, no scroll-reveals/page-load animation sequences (≤150ms fades only).

## Data model facts (verified against live DB, 2026-08-14)

- `products` — 100 rows, all `tracked=1`. Fields: `category` (cpu/gpu), `brand`, `model`, `variant` (nullable), `vram_gb`/`cores`, `generation_tier` (current ×28, current-1 ×38, current-2 ×34), `tracked`, `last_snapshot_at`, `created_at`.
- `retailer_listings` — 335 rows. `product_id` FK, `retailer` (scorptec ×205, pccg ×130), `variant_name` (**89 rows contain commas** — truncate to first segment for compact display), `listing_url`, `status`, `last_snapshot_at`.
- `price_snapshots` — 1098 rows. `retailer_listing_id` FK, `snapshot_date` 'YYYY-MM-DD', `price_aud` REAL, `stock_status` enum, `scraped_at`. Append-only, `UNIQUE(listing, date)`. Dates: 09–13 Aug (coverage 56/95/317/315/315).
- History depth: 1pt ×15, 2pt ×10, 3pt ×226, 4pt ×35, 5pt ×49 listings. **Movers/change floor = 3+ snapshots**; below that show "not enough history yet", never 0% or blank.
- 35 products have listings at both retailers.
- Indexes: `idx_products_category_tracked`, `idx_retailer_listings_product`, `idx_retailer_listings_status`, `idx_snapshots_listing_date`, `idx_snapshots_date`. DB is WAL. Never delete rows (SPEC §7a); never present stale data as current — show freshness from `last_snapshot_at`.

## Steps

### M0 — Scaffold
1. `npx sv create` SvelteKit (TS, adapter-node) into `web/`; add Tailwind v4 via `@tailwindcss/vite`.
2. Verify better-sqlite3 native build on this machine.
3. `.gitignore`: `web/node_modules`, `.svelte-kit`, `web/build`.

### M1 — Design foundations
4. `src/app.css`: CSS-variable tokens only (flat neutrals, hairline borders, muted text, one accent, semantic `--up/--down/--flat/--stale`, 4–8px radii, no shadows). `data-theme` dark-default + light mode. `.num` utility: mono stack + `tabular-nums`. Sentence case, 2 weights.
5. `src/lib/theme.ts`: dark/light toggle persisted in localStorage, default dark.
6. Primitives in `src/lib/components/`: `Badge` (dot+label chip), `StatTile`, `PriceChange`, `Filters`, `Header` + `+layout.svelte`.

### M2 — Server data layer (`src/lib/server/`)
7. `db.ts`: better-sqlite3 singleton, read-only, `busy_timeout=5000`, never toggle journal mode. Path from `TRACKAROO_DB` env, default `../../db/trackaroo.db`. Typed row interfaces.
8. Repos: `getSummary()`, `getLatestListings(filters)` (latest + window-start price per listing + freshness), `getProductHistory(productId)` (all variants), `getMovers(windowDays)` (3+ point floor → `not_enough_history` flag).
9. `src/lib/formats.ts` (AUD, pct, relative dates, freshness) + `src/lib/change.ts` (up/down/flat/stale classifier).

### M3 — Views
10. Dashboard `/`: stat row (tracked products, listings today, retailer count, biggest mover) + dense latest-prices table (model, category, retailer, variant, mono price, stock chip, 7-day change chip, freshness). Graceful "new listing"/"no data in window" cells.
11. Product `/product/[id]`: meta header, all variants side-by-side, `PriceChart.svelte` (uPlot, one series/listing, single hue + line styles, custom tooltip).
12. Movers `/movers`: 24h/7d/30d window, sortable (abs/pct/price), up/down filter, not-enough-history states.
13. Filters (category/retailer/generation tier) via URL `searchParams`, `goto`-driven.

### M4 — Polish & verify
14. Empty/stale/not-enough-history states everywhere; §7a freshness wording.
15. Dark/light parity + tabular-alignment audit; chart tooltip token-styled.
16. `npm run build`, `npm run check`, lint, `npm run preview` against real DB.

### M5 — Tests & docs
17. vitest: repo queries + load functions on temp DB from `data/*.json`; component smoke tests.
18. Update `README.md`, `STATUS.md`, `DECISIONS.md` (chart lib, theme strategy, DB path).