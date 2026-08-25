# Product index: a search-first GPU/CPU page

## Problem

`/products` is a filter-and-sort card grid: six `<select>` controls, a debounced
text box, and one card per product with a sparkline, a stock summary and an
expandable listing table. It was built to *browse* a catalogue.

That is not what it is used for. The stated job is **"find a model I already
have in mind"** — you arrive knowing you want an RTX 5070 Ti and you want its
price. Against that job the grid is actively hostile:

- **The controls answer the wrong question.** Category, retailer, brand,
  generation, sort and search are six ways to narrow a set. Someone who knows
  the model name needs one.
- **Cards are low-density.** 100 tracked products at roughly 150px of card
  height each; finding a known model means scrolling past dozens of irrelevant
  ones or fighting a filter.
- **It degrades with every launch.** 100 products across three generations
  today. Each new generation adds ~15 and pushes the target further down.
- **Search costs a round trip.** The text box debounces 450ms and re-queries
  the server, so narrowing 47 products — a payload of a few kilobytes — takes a
  network hop per keystroke burst.

Meanwhile the nav now treats category as a *place* (`GPUs`, `CPUs` →
`/products?category=…`), so the category select duplicates the navigation, and
`/deals` and the homepage already answer "what is worth buying" and "what
changed". `/products` does not need to answer those too.

## Approach

Rebuild `/products` as a **search-first index**: one search box and one dense
row per product, filtered in the browser.

The whole category (~47 GPUs or ~53 CPUs) is sent to the client on load. That is
a few kilobytes, so filtering is instant and local — no debounce, no round trip,
no loading state. This is the opposite of the `/deals` and chip-facet decision
in the price-first IA spec (§7), and deliberately so: there the result set is
listings and too large to ship; here it is one row per *product* and small
enough that shipping it is cheaper than querying it.

## Design principles

- **One job, done fast.** Reaching a known model is the page's purpose. Every
  other affordance must justify itself against that.
- **Density over decoration.** A row, not a card. No sparkline, no expandable
  listing table — those belong on the product page.
- **Structure that survives growth.** Grouping comes from generation data the
  DB already has, so a new generation slots in without a code change.
- **Don't duplicate neighbours.** `/deals` owns value. The homepage owns
  movement. This page owns *finding*.

## 1. The page

`/products?category=gpu` (the `GPUs` nav destination) renders:

```
GPUs                                          47 tracked
┌──────────────────────────────────────────────────────┐
│ 🔍 Search 47 GPUs…                          ☐ In stock│
└──────────────────────────────────────────────────────┘

── NVIDIA · RTX 50 (Blackwell) ────────────────────────
  ☐ GeForce RTX 5060        $549   ▼3.0%  Scorptec
  ☐ GeForce RTX 5060 Ti     $729   ▼3.7%  Scorptec
  ☐ GeForce RTX 5070      $1,099   ▲2.1%  Scorptec
── NVIDIA · RTX 40 (Ada) ──────────────────────────────
  ☐ GeForce RTX 4060        $429     —    PCCG
```

**Search box** — autofocused on load, `type="search"`, placeholder naming the
count. Filtering is local and immediate.

**Empty query** → the full category, grouped (§3).

**Non-empty query** → group headers disappear, results become one flat list
ranked by match quality (§2), preceded by a live count: `3 of 47 match`.
**Enter** navigates to the top hit. **Escape** clears the box.

**No results** → `No GPUs match "5090 ti".` plus a button to clear.

## 2. Matching and ranking

Matching moves into `web/src/lib/productSearch.ts` as a pure function, and
**`CommandPalette` uses the same function**. Two search surfaces that rank the
same catalogue differently would be a bug waiting to happen; today the palette
does an unranked substring `filter`, so it also gains ranking for free.

Query is lowercased and whitespace-collapsed. A product matches if every
whitespace-separated term appears in its haystack (`model` + `brand` +
`productVariant`), so `5070 ti` and `ti 5070` both find the same card.

Ranked, best first:

1. Exact match on the model name
2. Model starts with the query
3. Query matches at a word boundary in the model
4. Substring anywhere in the model
5. Match only via brand or variant

Ties break on model name, so ordering is stable and testable.

## 3. Grouping and order

Group key is `(brand, generation_tier)`. The label comes from the **existing**
`generationTierLabel(brand, category, tier)` in `web/src/lib/tiers.ts`, which
already yields `RTX 50 (Blackwell)`, `RX 9000 (RDNA 4)`, `Ryzen 9000 (Zen 5)`.
No new derivation, and a new generation gets a header as soon as the watchlist
tags it.

**Order is brand-major, newest generation first within each brand.** Brands are
ordered by tracked-product count descending, so the biggest catalogue leads and
a newly added brand lands predictably rather than jumping the queue.

Rationale for brand-major over strictly-newest-across-brands: buying is usually
brand-anchored — you are looking at NVIDIA *or* AMD — so keeping a brand's
generations adjacent matches how the list is scanned. The cost is that an older
NVIDIA generation sits above a newer AMD one, which is acceptable because the
headers make the generation explicit.

Headers do **not** collapse. They are scroll anchors, not controls: collapsing
would add a click to the very task the page exists for.

## 4. The row

| Element | Source | Notes |
|---|---|---|
| Compare checkbox | client state | Same 2–4 same-category rule as today |
| Model | `products.model` | The click target; opens `/product/{id}` |
| Cheapest in-stock price | existing group data | `—` when nothing is in stock |
| Change vs its own average | `avg30` + `avg30Points` | Uses `avgWindowLabel()`, so it states real evidence |
| Retailer | of that cheapest price | Which shop the price is at |

Deliberately **not** on the row: sparkline, deal badge, listing count,
expandable listing table, stock breakdown. Each is either on `/deals`, on the
homepage, or one click away on the product page.

The floating compare bar (`2 selected · Clear · Compare →`) is unchanged.

## 5. What is removed

- `ProductCard.svelte` and the card grid
- The category, retailer, brand, generation and sort `<select>`s in
  `Filters.svelte` — category is the page, generation is a header, sort is
  fixed, and brand/retailer are covered by search
- The retailer chip row added in price-first IA stage 4 (it was a stopgap for
  the select; the search box supersedes it)
- Server-side text search, sort and the 450ms debounce for this route

**`Filters.svelte` ends up with no consumer and is deleted.** The in-stock
toggle survives as a plain checkbox beside the search box.

## 6. Data

One query per page load returning one row per tracked product in the category:
`id, brand, model, generation_tier, cheapestInStockPrice, retailer, avg30,
avg30Points, inStockCount`. `getDealCandidates` already computes the price and
average figures for exactly this shape; the index needs the same numbers plus
products with **no** in-stock listing today (which `getDealCandidates` excludes
by design), so it gets its own query rather than bending that one.

Payload is ~50 rows; no pagination, no virtualisation. If a category ever
exceeds a few hundred products, revisit — not before.

## 7. The Intel Arc data problem

All five Arc cards are tagged `generation_tier = 'current'`, but A380/A750/A770
(Alchemist) and B570/B580 (Battlemage) are different generations. There is also
no `intel-gpu` entry in `TIER_LINE_LABELS`, so they would fall back to the
generic `Current gen`.

Both are fixed as part of this work — retagging Alchemist as `current-1` in the
watchlist and adding `intel-gpu` labels — because the headers are the page's
backbone and would be visibly wrong on day one otherwise.

## 8. UI/UX conventions

Inherited unchanged from the price-first IA spec: tokens only; direction never
carried by colour alone; `.num` for figures; one accent; reduced motion
respected; `aria-live` on the result count; no runtime imports from
`$lib/server/…` in client components.

Additions specific to this page:

- The search box is a real `<label>`-ed control, not a placeholder-only input.
- Group headers are `<h2>`, rows are links, so the page is navigable by heading
  and by link with a screen reader.
- Keyboard: `/` focuses search from anywhere on the page, `Enter` opens the top
  hit, `Escape` clears.

## 9. Testing

- **Vitest** on `productSearch.ts` (matching, multi-term, ranking order, tie
  breaks) and on the grouping/ordering helper (brand-major, newest-first,
  unknown tier falls back).
- **Vitest** on the row and the index component: renders `—` with no in-stock
  price, uses `avgWindowLabel`, compare checkbox reflects state.
- **E2E**: typing narrows the list and the count; Enter opens the top hit;
  clearing restores the groups; the compare flow still reaches `/compare`;
  headers render when the box is empty; the seeded fixtures are used, never
  scraped-live values.
- **Full validation**: `pytest`, `npm run check`, `npm test`,
  `npm run test:e2e`, `npm run build`, plus a Docker build-and-boot per
  `CLAUDE.md`.

## 10. Out of scope

- Any change to `/deals`, the homepage, `/movers` or the product page
- Cross-retailer variant matching
- Virtualised scrolling or pagination
- Spec-based filtering (VRAM, cores) — a different job, and the spec data is
  only ~95% covered

## Open risks

- **Brand-major ordering is a judgement call.** If scanning by recency turns
  out to matter more than brand adjacency, the fix is to change the group
  comparator — the grouping data does not change.
- **Removing sort may be missed.** Ordering is now fixed. If sorting by price
  proves necessary, it belongs as an explicit control, not by restoring six
  selects.
- **`/` as a focus shortcut can swallow typing** if a future control on the page
  takes text input. It must be ignored when focus is already in a field.
