# Price-first information architecture

**Date:** 2026-08-23
**Status:** Approved design, not yet implemented
**Scope:** `web/` only. No pipeline, scraper or schema changes.

## Problem

Trackaroo exists to highlight good deals and to track price drops and rises on
AU CPUs and GPUs. The current UI does not organise itself around that purpose.

**The nesting does not scale.** The product page nests
product → brand → retailer listing. Brand is not a stored field: it is parsed
out of the raw scraped name at render time by `deriveListingBrand()`
(`web/src/lib/branding.ts`), and grouped by `buildBrandGroups()`
(`web/src/lib/listingsPanel.ts`). With two retailers a brand accordion holds
two to four rows. At six retailers (Scorptec, PCCG, MWave, Umart, Centre Com,
PLE Computers) a popular GPU reaches 50–100 listings behind roughly eight
accordions.

Worse, neither nesting level answers the question the visitor arrives with.
Someone opening an RTX 5070 Ti wants "cheapest right now, and is that price
actually good". Brand grouping puts three clicks in the way.

**The deal signal is computed and discarded.** `ProductGroup.deal` and
`ProductGroup.avg30` already exist in `web/src/lib/server/repos.ts`, but the
flag only renders a badge on a card. There is no page that answers "what is
cheap today".

**The homepage reads as a database, not a deals site.** Three of four stat
tiles are inventory counts (`Tracked products`, `Listings today`, `Retailers`).
The dominant element is a filterable listing table, which is a browsing tool.

**Nothing surfaces a retailer going dark.** With six retailers the realistic
failure is one scraper silently failing while the site still looks healthy. A
tracker missing a retailer is not merely incomplete: its "cheapest price" is
wrong.

## Approach

Three alternatives were considered.

**A — Variant-first matrix.** Add a normalised `variant_key` in the Python
pipeline so the same physical card matches across retailers, then show one row
per card with a price cell per retailer. Best end state, but it needs a fuzzy
matching layer in ingest, carries real data-integrity risk (a bad match merges
two different cards and corrupts price history), and blocks all UI work behind
pipeline work.

**B — Price-ranked flat list with facets. CHOSEN.** Remove the brand accordion.
One list per product sorted cheapest-in-stock first. Brand and retailer become
visible attributes on each row and filter chips above the list, rather than
levels inside it. Scales to six retailers for free, because sorting does the
work nesting was doing badly. No pipeline change.

**C — Brand groups collapsed to one summary row each.** Preserves a hierarchy
level that does not serve the visitor; still yields eight accordions at six
retailers.

B is chosen. Nearly all the UX payoff, decoupled from the pipeline, which
matters because four retailers are due to be added and the display should not
be mid-rewrite while ingest changes. A is deferred to its own spec.

## Design principles

1. **Price leads.** The cheapest buyable price is the largest element on any
   surface that shows one.
2. **Sort, do not nest.** Attributes become row metadata and filter chips.
3. **Every number earns its place.** Provenance (snapshot counts, history
   spans) is demoted to muted secondary text or moved to the health strip.
4. **Deal and mover are different things** and both are shown. See §5.
5. **Symmetry between CPU and GPU**, which also matches the Discord digest
   shape (`cpu:up`, `cpu:down`, `gpu:up`, `gpu:down`) in `notify_discord.py`.

## 1. The offer row

The single repeated unit. Used by the product page, `/deals`, and the homepage
category sections.

```
$1,299   ASUS TUF Gaming RTX 5070 Ti OC 16GB       ▼ 8% vs 30d avg
         ASUS  ·  Scorptec  ·  updated 2h ago      In stock    View →
```

**Contents and behaviour**

- Price leads, left-aligned, largest text in the row, `font-mono` via the
  existing `.num` class so columns align.
- Variant name is the row title, truncated with a `title` attribute for the
  full string.
- **Brand and retailer appear on every row** as a muted metadata line. They are
  never hidden behind a disclosure.
- Delta vs that product's 30-day average, coloured with `--down` when below
  (good) and `--up` when above. Rendered only when
  `avg30Points >= MIN_HISTORY_POINTS`; otherwise the slot shows
  "not enough history" in `--text-muted`.
- Stock state via the existing `StockBadge`; `Delisted` via the existing
  `Badge` with tone `stale`.
- `View →` links to `listing.listing_url` with `target="_blank"` and
  `rel="noopener noreferrer"`, matching current behaviour.

**Ordering.** Cheapest in-stock first. Out-of-stock rows sort below a labelled
divider. Delisted rows last. Never interleave: an out-of-stock $999 above an
in-stock $1,099 would misrepresent what is buyable.

**Data.** All present on `Series`: `listing.retailer`, `listing.variant_name`,
`listing.listing_url`, `listing.status`, plus `deriveListingBrand()`. No schema
change.

**Responsive.** Below `sm`, the row becomes two lines: price and delta on the
first, brand/retailer/stock on the second. `View →` becomes the whole-row tap
target on touch, with the metadata line remaining visible.

## 2. Product page: OfferList replaces BrandGroupedListings

Flat cheapest-first list of offer rows, with facet chips above it.

```
Retailer:  [All 18] [Scorptec 6] [PCCG 4] [MWave 3] [Umart 3] [PLE 2]
Brand:     [All 18] [ASUS 5] [Gigabyte 4] [MSI 4] [ZOTAC 3]
                                        [x] In stock only (18 of 31)

   … 8 offer rows, cheapest first …

              [ Show all 31 offers ]
```

- Chips filter client-side over already-loaded data. No server round-trip, so
  filtering is instant.
- Each chip shows its result count.
- **A chip row hides itself when it would offer only one value.** A CPU with no
  AIB brands shows no brand row at all, rather than a row with one useless
  chip.
- Chips are `<button aria-pressed>`, keyboard reachable, with
  `--accent-soft` background when active.
- The existing free-text filter carries over.

### Volume control: the two defaults that make the page short

Flattening the accordions removes *repetition* but not *volume* — 50 listings
is still 50 rows. Sorting means you need not read them; it does not stop them
being there. These two defaults are what actually shorten the page, and
together they recover most of the benefit of approach A at none of its risk.

**1. "In stock only" defaults to ON.** It is currently
`inStockOnly = $state(false)` in `BrandGroupedListings.svelte`. Out-of-stock
listings are noise for someone shopping today, and on a popular GPU they are
frequently half the rows.

- The control **states what it is hiding**: "In stock only (18 of 31)". Nothing
  is silently disappeared, and the escape hatch is one click.
- When a product has **no in-stock listings at all**, the filter auto-disables
  itself and the list renders every offer with an explanatory line — otherwise
  the default would produce an empty page for a product that plainly has
  prices, which reads as a bug.

**2. Progressive disclosure: 8 rows, then "Show all N offers".** Deliberately
the inverse of today's page, which hides everything behind accordions by
default. Show the answer immediately; put the long tail one click away.

- The threshold is 8. Below 9 offers the expander does not render at all.
- The button states the true total ("Show all 31 offers") so the page never
  conceals the size of what it holds.
- Expansion is client-side only — the rows are already loaded.
- The count respects active chips: filtering to Scorptec re-computes both the
  visible 8 and the "show all" total.
- `aria-expanded` on the button; focus stays put on expand so keyboard users
  are not thrown to the bottom of a 50-row list.

**Interaction between the two.** The stock filter applies first, then the
8-row cap. A product with 31 offers of which 18 are in stock shows 8 rows and
a "Show all 18 offers" button — the cap counts what the filter left, not the
raw total, or the numbers would contradict each other.

`buildBrandGroups()` is removed. `toListingDisplays()` and `priceRange()`
survive unchanged and keep their tests.

**Chart interaction is preserved.** The "Show on chart" toggle stays on each
offer row, driving the same `selected` set and overlay behaviour on
`PriceChart`.

## 3. Product page headline

Currently eight `Chip`s at identical visual weight
(`Category`, `Generation`, `All-time low`, `All-time high`, `30d avg`,
`Listings`, `History span`, `Snapshots`), and the current price is absent
entirely.

```
RTX 5070 Ti
NVIDIA  ·  Blackwell

  $1,299            ▼ 8% vs 30d avg   ·   ▲ 4% above all-time low
  at Scorptec

  all-time low                        today             all-time high
  $1,249  ├──────────────●─────────────────────────────────┤  $1,689

  6 listings  ·  47 snapshots  ·  12 Mar – 23 Aug 2026
```

- **Current cheapest in-stock price** is the headline number, with its
  retailer beneath.
- **Two deltas** answer "is now a good time": against the 30-day average and
  against the all-time low.
- **Position-in-range bar.** A horizontal track from all-time low to all-time
  high with a marker at today's cheapest. Highest-value new element on the
  page: it answers the buying question at a glance.
  - Accessible as `role="img"` with an `aria-label` stating the three figures
    in words, since the visual encoding alone is not readable by assistive
    tech.
  - Degrades to a plain "low / today / high" text line when
    `allTimeHigh === allTimeLow` (a single-price history), where a bar would
    be meaningless.
- Listings / snapshots / history span become one muted line. Category and
  generation move beside the title.
- The existing `avg30` / `MIN_HISTORY_POINTS` guard is retained: with thin
  history the deltas render as "not enough history", never a misleading
  number.

## 4. /deals

Promotes the already-computed deal flag to a destination.

- One offer row per product, **ranked by depth below its own 30-day average**:
  `(avg30 − cheapestInStockPrice) / avg30`, deepest first.
- **Two sections**, because they are different strengths of signal:
  - **Below 30-day average** — the main list.
  - **At or near all-time low** — anchored at `#all-time-low`. Called out
    separately rather than blended into one score, because it is the stronger
    claim. **"Near" means within 2% of the all-time low**; a product may appear
    in both sections, which is correct — it is both cheap versus recent history
    and cheap versus all history.
- Category, retailer and brand facets reuse the §2 chips.
- Only products with `avg30Points >= MIN_HISTORY_POINTS` are eligible. A
  product with three days of history has no meaningful average and must not be
  presented as a deal.
- **Empty state gets real copy**, not a blank panel: "No products are below
  their 30-day average today." A quiet day is information, not a broken page.

## 5. Homepage dashboard

```
┌─ Data health ──────────────────────────────────────────────────────┐
│ ● Updated 2h ago · 23 Aug 2026         47 days · 12,483 snapshots  │
│ Scorptec ✓2h   PCCG ⏸ cooling down   MWave ✓2h   Umart ⚠ 2d       │
└────────────────────────────────────────────────────────────────────┘

┌─ GPUs ─────────────────── 84 tracked · cheapest $329 · All GPUs → ─┐
│  Top deals            Biggest drops (7d)      Biggest rises (7d)   │
│  3 offer rows         3 rows                  3 rows               │
└────────────────────────────────────────────────────────────────────┘

┌─ CPUs ─────────────────── 52 tracked · cheapest $189 · All CPUs → ─┐
│  (identical shape)                                                 │
└────────────────────────────────────────────────────────────────────┘
```

Answers three questions in priority order: can I trust this data, is anything
worth buying, what changed.

### Deal and mover are not the same thing

| | Question | Time frame |
|---|---|---|
| **Deal** | Is this cheap for what it is? | vs its own 30-day average |
| **Mover** | What just happened? | vs the start of the window |

A card can drop 10% and still be poor value; a card can be excellent value with
no movement at all. Neither list contains the other, which is why both appear.
Rises are shown as well as drops, because tracking increases is part of the
product's stated purpose — a rise is the "buy before it climbs further" signal.

### Decision: 7-day mover window on the homepage

The scrape cadence is daily, so a 24-hour window is a single snapshot pair and
one missed run empties the section. The homepage uses 7 days for robustness.
The window selector remains on `/movers` for the sharper view.

### Decision: health strip at the top

One slim row. "Is this current?" genuinely precedes "is this cheap?", and a
stale retailer invalidates the deal lists below it.

### Health strip states

- **Fresh** — snapshot today. Neutral/positive marker.
- **Cooling down** — an intended circuit-breaker pause. Uses a distinct
  informational treatment, **not** an error colour. The PCCG breaker is working
  as designed (see `CLAUDE.md`); the UI must not cry wolf about it.
- **Stale** — no snapshot in ≥ 2 days. Warning treatment.

Colour is never the only carrier: each pill states its age in text.

**Implementation, staged to avoid new coupling.**

- *Baseline, this spec:* per-retailer freshness from the DB alone —
  `MAX(snapshot_date) GROUP BY l.retailer`, in the manner of the existing
  grouped query at `repos.ts:955`. This distinguishes fresh from stale with no
  new dependency.
- *Follow-up, not this spec:* distinguishing "cooling down" from "stale"
  requires the web app to read `data/pccg_cooldown.json`, coupling it to the
  pipeline's file layout. `health_checks.py:837` `check_scraper_cooldown()`
  already models this state Python-side. Deferred deliberately.

Until the follow-up lands, a cooling-down retailer displays as stale. That is
honest — its data *is* older — just less specific.

### What the homepage replaces

- **The four stat tiles are removed.** `Tracked products` and `Retailers`
  become small text in section headers. `Listings today` and `Biggest mover`
  are absorbed by the health strip and the movers columns.
- **`CheapestCarousel` is folded in** as the "cheapest $329" figure in each
  section header, removing duplication with the category sections.
- **The filtered listing table moves to `/products`.** A filter-and-sort table
  is a browsing tool; keeping it on `/` is what makes the homepage read as a
  database.

### Homepage data requirements

| Piece | Status |
|---|---|
| Top deals per category | `ProductGroup.deal` + `avg30` exist; needs depth ranking |
| Biggest drops/rises per category | `Mover` exists; needs a category split |
| Cheapest per category | `CheapestListing` exists |
| Tracked count per category | Trivial count |
| Per-retailer last snapshot | **New query** — the only real addition |

### Homepage empty states

Every section needs deliberate copy, because early in a product's life several
will be empty at once:

- No deals: "Nothing below its 30-day average today."
- No movers: "No significant price moves in the last 7 days."
- Insufficient history: "Not enough history yet — deals appear once a product
  has `MIN_HISTORY_POINTS` days of prices."

## 6. Navigation and header

```
● Trackaroo    Deals   GPUs   CPUs   Movers   Compare     [Search Ctrl+K]  ☀
```

- **Deals first.** The site's purpose gets the first slot.
- **GPUs / CPUs replace Products.** Category becomes a place rather than a
  filter re-applied on every page. Both are `/products?category=…`, so
  `Header.svelte` must match active state on the query string. Its current
  check is `path === link.href` against `pathname` only, which would never
  highlight either link.
- **Compare joins the nav**, ending its orphan status (the route exists but is
  reachable only via checkboxes on `/products`). Opened with no `ids`, it
  renders an empty state explaining how to select products.
- **DB size and snapshot-day count move out of the header** into the health
  strip, which is their honest home. The user-facing staleness signal is
  already handled by `StaleDataBanner`.
- Below `md` the nav collapses to a horizontally scrollable row rather than a
  hamburger; five short items fit, and a menu would add a tap to every
  navigation.

## 7. Designed for six retailers

Display-side preparation, so the UI is ready before the scrapers land:

- Extend `RETAILER_OPTIONS` in `web/src/lib/filters.ts` (currently only
  `scorptec` and `pccg`) and the `Retailer` type.
- The retailer `<select>` in `Filters.svelte` becomes a chip row that *looks*
  like §2 but is **not** the same mechanism, and this distinction must not be
  collapsed during implementation:
  - **Product page chips (§2)** filter an already-loaded list client-side.
    Instant, no navigation.
  - **`/products` and `/deals` chips** are URL-driven and filter server-side
    via `goto()`, exactly as the current `<select>` controls do. The result set
    is too large to ship to the client.

  They share presentation (a `Chip`-style button with a count) and nothing
  else. Build one presentational component; drive it from two different places.
- Extend `RETAILER_LABELS` in `notify_discord.py:52`, or the Discord digest
  prints raw slugs for the new retailers.

**The four scrapers are out of scope.** Each needs its own reconnaissance (API
vs HTML, rate limits, SKU extraction) and PCCG has shown how much that varies.
Each gets its own spec.

## 8. UI/UX conventions

- **Tokens only.** All colour comes from the existing tokens in
  `web/src/app.css` (`--bg`, `--surface`, `--surface-hover`, `--border`,
  `--text`, `--text-muted`, `--accent`, `--accent-soft`, `--up`, `--down`,
  `--flat`, `--stale`). Both light and dark are defined; no new hex values.
- **Direction is never colour-only.** Every up/down indicator carries an arrow
  glyph and a signed number, so it survives colour-blindness and greyscale.
- **Numbers are monospaced** via `.num` so prices align down a column.
- **One accent.** `--accent` is reserved for interactive affordances. Deal
  emphasis uses `--down`; it must not compete with the accent.
- **Reduced motion respected**, following the existing
  `@media (prefers-reduced-motion: reduce)` pattern in `+layout.svelte`.
- **Live regions retained.** The existing `aria-live="polite"` result-count
  announcements on filter changes carry over to the chip facets.
- **Client/server boundary.** Chip and offer-row components must not import
  runtime values from `$lib/server/...`; shared constants go in
  `web/src/lib/constants.ts`.

## 9. Testing

- **Pure logic in `web/src/lib/`** with Vitest, alongside the existing
  `filters.ts` / `listingsPanel.ts` tests: offer sorting (including the
  in-stock/out-of-stock/delisted partition), facet counts, deal depth ranking,
  range-bar position, per-retailer freshness classification.
- **The §2 volume defaults specifically**, since they are the parts most likely
  to produce a confusing page when they interact:
  - stock filter applied before the 8-row cap, so the expander's total matches
    what the filter left;
  - a product with zero in-stock listings auto-disables the filter rather than
    rendering empty;
  - no expander below 9 offers;
  - chip filtering re-computes both the visible slice and the expander total.
- **E2E** (`web/e2e/app.spec.ts`): `/deals` renders and ranks correctly, nav
  reaches every page with correct active states, chip facets filter. The
  seeded DB (`e2e/seed.mjs`) needs a deliberate below-average fixture, an
  at-all-time-low fixture, and a stale-retailer fixture. All navigation via the
  local `goto()` helper. Suite stays under the ~60s goal.
- **Full validation:** `python -m pytest -q` at the repo root, then from
  `web/`: `npm run check` (0 errors), `npm test`, `npm run test:e2e`.

## 10. Implementation sequencing

This spec is larger than one sitting. It decomposes into four stages, each
independently shippable and independently verifiable, in this order:

1. **The offer row + product page (§1, §2, §3).** Must come first: the offer
   row is the unit every later stage reuses, and the product page is where the
   nesting pain is worst today.
2. **`/deals` (§4).** Consumes the offer row. Small once stage 1 exists,
   because the ranking data is already computed.
3. **Homepage dashboard (§5).** Consumes the offer row and needs the one new
   query (per-retailer freshness).
4. **Nav, header and six-retailer prep (§6, §7).** Last, because it points at
   pages that must already exist — shipping a `Deals` nav link before `/deals`
   exists would ship a broken site.

Each stage ends with the full validation in §9 passing before the next begins.

## 11. Out of scope

- **Cross-retailer variant matching (approach A).** Its own spec, after the
  new retailers are landing data. It changes listing identity, which
  `CLAUDE.md` flags as the most sensitive area of the pipeline.
- **Writing the MWave, Umart, Centre Com and PLE scrapers.**
- **Reading `data/pccg_cooldown.json` from the web app** (§5 follow-up).

## Open risks

- **Removing the homepage listing table** is the most opinionated change. If
  the table turns out to be the primary way it is actually used, the fix is to
  add a "Latest prices" link to `/products`, not to restore the table.
- **Deal depth ranking favours volatile products.** A card that swings widely
  will surface more often than a steadily good-value one. Acceptable for now;
  revisit if the list feels repetitive.
- **Position-in-range needs enough history to be meaningful.** Guarded by the
  degradation rule in §3, but on a young dataset most products will show the
  text fallback.
