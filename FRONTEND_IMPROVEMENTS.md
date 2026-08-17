# Trackaroo Frontend Improvements — Implementation Brief

**Context for whoever implements this:** Trackaroo is a self-hosted AU CPU/GPU price tracker. Backend (scraper, SQLite schema, ingestion) is fully built — see `STATUS.md`, `SPEC.md`, `SCOPE_RULES.md`, `DECISIONS.md` in the repo root for full context; read those first if you haven't. This doc covers frontend/UX improvements only. The current dashboard (screenshot reviewed) is a plain data table — functional, but doesn't help the user *find deals*, which is the actual product goal per `SPEC.md` §4.

**Read this whole doc before implementing anything** — items reference each other (e.g. the sparklines use the same price-history data the movers views already query).

---

## 1. Deal Score

> **STATUS: DECLINED (2026-08-17)** — the user decided not to build the deal score. This item is scrapped from the plan; nothing downstream depends on it (the carousel shipped without it, and the sparklines use raw price history directly).

**Problem:** nothing in the current UI tells the user "this is a good deal" vs. "this is just a listing." Price and stock are shown, but there's no signal for *is this worth buying now*.

**What to build:** a computed `deal_score` per retailer_listing, based on where the current price sits relative to its own history:

```sql
-- Sketch — adapt to query.py's existing patterns
deal_score = (historical_max_price - current_price) / (historical_max_price - historical_min_price)
-- 1.0 = at its all-time low, 0.0 = at its all-time high
```

Requires at least ~2 weeks of snapshot history per listing to be meaningful — with one day of data, everything will show as "at its low" trivially. **Gate this feature behind a minimum history length** (e.g. don't show a deal score until a listing has 7+ snapshot days), and show "Gathering price history" instead of a misleading score in the meantime.

Also compute, per listing, alongside deal_score:
- `pct_below_30d_avg` — simpler, more intuitive to display than raw deal_score ("12% below its 30-day average")
- `is_all_time_low` (bool) — for a clean badge

## 2. Product images

> **STATUS: DECLINED (2026-08-15)** — the user decided not to add product images. This item is scrapped from the plan; placeholder icon fallbacks are only used where a row already needs an image (none currently).

**Problem:** you said it yourself — no visual identity. For GPUs/CPUs, people recognize products by box art and cooler shroud design as much as by name text. A text-only row is much slower to scan than one with a thumbnail.

**Implementation:**
- Add `image_url` column to `retailer_listings` (schema migration — add a `DECISIONS.md` entry when you do this, per existing project convention)
- Capture the image URL during scraping — Scorptec and PCCG product listings/API responses include image URLs already; just parse and store them alongside price
- **Recommendation: hotlink, don't rehost.** Reference the retailer's own image URL directly in the `<img src>` rather than downloading and re-serving the image yourself. This keeps you consistent with the project's existing politeness/ToS principle (`SPEC.md` §10) — displaying a linked product image for identification is materially different from copying and redistributing retailer assets. Add a fallback placeholder icon (generic GPU/CPU silhouette by category) for rows where the image fails to load.

## 3. Switch the Products view from table rows to cards

> **STATUS: DONE (2026-08-16)** — shipped as the `ProductCard` grid on `/products` (grouped by product, expandable variant listings, `LatestListingTable` in compact mode). No product images (item 2 declined); no deal-score badge (item 1 declined).

**Problem:** with 100+ products and growing, and especially once you're showing multiple AIB variants (8 RTX 3050 listings in the screenshot alone), a flat table gets overwhelming fast, and it's the wrong shape for deal-browsing anyway — people scan deal sites visually, not row-by-row.

**Implementation:**
- Card layout for the **Products** page: model name, retailer badge, price, stock badge
- Keep the **dense table** for the **Movers** page — that's a comparison/analysis view where density is actually useful, unlike Products which is a browsing view
- Group multi-variant listings under one expandable product card where practical (e.g. "GeForce RTX 3050 — 8 listings from $269" expands to show each variant), rather than 8 separate top-level rows — reduces visual noise significantly as the watchlist grows

## 4. "Cheapest per model" GPU carousel — for the dashboard

> **STATUS: DONE (2026-08-17)** — shipped as the `CheapestCarousel` with a GPU/CPU toggle (resolved the GPU-only vs +CPU scope question below); each card shows model, cheapest in-stock price at the latest snapshot, retailer, and a 90d-low badge.

Revised from the original "Best Deals" idea — this version has **no dependency on accumulated price history**, so it can ship immediately rather than waiting on weeks of data.

**Placement:** top of the Dashboard, above the current stat cards or directly below them.

**Content:** horizontally-scrollable row of cards, one per distinct GPU model currently tracked (RTX 5090, RTX 5080, RTX 5070 Ti, RX 9070 XT, etc.) — not per generation tier, per specific model. Each card shows: the model name, its cheapest current in-stock price across both retailers, and which retailer has that price. Example, per the user's spec:

```
RTX 5090 ......... $1,202  Scorptec
RTX 5080 ......... $1,230  PCCG
RTX 5070 Ti ...... $[...]  [retailer]
```

**Query shape:**
```sql
-- Sketch — adapt to query.py's existing patterns.
-- For each distinct model, find the lowest price among today's in-stock listings.
SELECT
    p.model,
    r.retailer,
    ps.price_aud
FROM products p
JOIN retailer_listings r ON r.product_id = p.id
JOIN price_snapshots ps ON ps.retailer_listing_id = r.id
WHERE p.category = 'gpu'
  AND p.tracked = 1
  AND ps.stock_status = 'in_stock'
  AND ps.snapshot_date = (SELECT MAX(snapshot_date) FROM price_snapshots)
  AND ps.price_aud = (
      -- cheapest in-stock price for this product today, across retailers
      SELECT MIN(ps2.price_aud)
      FROM price_snapshots ps2
      JOIN retailer_listings r2 ON r2.id = ps2.retailer_listing_id
      WHERE r2.product_id = p.id
        AND ps2.snapshot_date = ps.snapshot_date
        AND ps2.stock_status = 'in_stock'
  )
GROUP BY p.id
ORDER BY p.model; -- or by a defined tier/performance order if you want the carousel in a specific sequence (5090 → 5080 → ...)
```

**Ordering note:** sorting alphabetically by model name won't give you 5090 → 5080 → 5070 Ti in the right order (string sort puts "5070" before "5080" before "5090" incorrectly relative to tier ranking desired... actually numeric sort works here since they're numeric substrings, but mixing NVIDIA/AMD or adding suffixes like "Ti"/"XT" will break a naive sort). Recommend adding an explicit `sort_rank` or `tier_rank` field to `products` (or deriving it from `SCOPE_RULES.md`'s per-model performance tier) so the carousel always renders in a sensible high-to-low order rather than relying on string/numeric sorting of the model name.

**Out of stock handling:** if a model has zero in-stock listings across both retailers on a given day, either omit it from the carousel that day or show it greyed out with "out of stock everywhere" — don't silently show a stale price from a delisted/out-of-stock listing as if it's currently available.

**Scope question to resolve before building:** should this carousel be GPU-only (as specified), or would a parallel CPU version (cheapest per CPU model) be worth building at the same time, given the same query pattern applies directly? Worth deciding now since the SQL and card component would be near-identical either way.

## 5. Inline sparkline instead of "New listing" pill

> **STATUS: DONE (2026-08-18)** — shipped as the `Sparkline` component: a 24px SVG polyline (up = red/coral, down = green/teal, flat = muted, dash when <2 points). Rendered as a "Trend" column between Price and Stock in `LatestListingTable` (products card rows, the dashboard table) and in the movers dense table (window-matched 24h/7d/30d), and on each unexpanded `/products` card showing the product's cheapest-in-stock-per-day line (`getSparklines` for listing series, `getProductSparklines` for card series). No uPlot needed for a bare trend line.

**Problem:** the "7-day change" column currently just says "New listing" for everything (expected, given the DB is one day old) — but even once history builds up, a text badge ("+5%" / "−12%") is less immediately scannable than a shape.

**Implementation:** a small inline sparkline (uPlot, already in the planned stack per `SPEC.md` §12) per row/card showing the last 7–30 days of price. Color the line red/green based on net direction. This becomes one of the highest-value additions once there's real history — it's the fastest way for a human eye to spot "this just dropped."

## 6. Priority order

Item 5 (sparklines) needed real price history to matter; the carousel (item 4, now shipped with a GPU/CPU toggle) had no such dependency. Product images (item 2) and the deal score (item 1) have been **declined** by the user and are dropped from the plan:

1. ~~Product images (item 2)~~ — declined by the user
2. ~~**Deal score** (item 1)~~ — **declined** (2026-08-17) — not building; the "is this a good deal" signal stays out of scope
3. ~~**Card layout for Products page** (item 3)~~ — **done** (one card per product, cheapest in-stock "from $X" + retailer, expandable per-variant listings; dense table kept on Movers/Dashboard)
4. ~~Cheapest-per-model GPU carousel (item 4)~~ — **done** (single carousel, GPU/CPU toggle, cheapest in-stock per model at latest snapshot)
5. ~~**Sparklines** (item 5)~~ — **done** (18-Aug): `Sparkline` component with a Trend column in `LatestListingTable` + movers table, and per-card trend lines on the `/products` grid

## 7. Documentation note

If any of these result in schema changes (item 2's `image_url` column is the only one that clearly does), update `db/schema.sql`, add an entry to `DECISIONS.md` explaining the addition, and note progress in `STATUS.md` — consistent with how the rest of this project has been maintained.
