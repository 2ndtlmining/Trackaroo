# Head-to-head matchups: design

**Date:** 2026-10-04 · **Issue:** #60 · follow-up to #33
**Status:** approved in conversation on 4-Oct-2026; awaiting written-spec review.

## 1. Purpose
On a product page, answer "is the rival from the other brand better value in AU today?" in one
sentence per metric. Example: "RTX 5070 Ti is 14% cheaper per frame than Radeon RX 9070 XT at
1440p raster".

### Owner decisions (4-Oct-2026)
- **Rivals are picked automatically, not curated.** The rule below picks them from the perf index
  and today's prices, so no list has to be maintained.
- **GPUs and CPUs both get matchups.** GPUs are NVIDIA vs AMD only. Intel GPUs get no panel and
  are never anyone's rival. CPUs are AMD vs Intel.
- **One rival per page**, which is what "one per other brand" works out to once Intel GPUs are
  excluded.
- **Matching:** the nearest score on the main metric, within 15%, with a VRAM tie-break.

### Rules carried over from the issue and #33
- Separate metrics. Raster and ray tracing get separate sentences and are never blended into one score.
- Every figure cites its source and its as-of date, the same way /value does.
- When either side has no perf data, or isn't in stock today, the panel shows nothing.

### Success criteria
- Every in-stock NVIDIA or AMD GPU, and every in-stock AMD or Intel CPU, with a main-metric score
  shows a matchup whenever a rival qualifies under §2. Every other product page shows no panel and
  no empty box.
- The figures agree with /value: the same prices (one price rule, #59) and the same perf numbers.
- All four test suites are green, axe passes in both themes, and nothing scrolls horizontally at 320px.

## 2. The rival rule
Inputs: the product being viewed (P) and the tracked products in the same category (the
candidates), each with its brand, VRAM, generation tier, today's price and perf scores.

- **Main metric:** `gpu_raster_1440p` for GPUs, `cpu_gaming_1080p` for CPUs.
- **Brands:** for GPUs the pair is {NVIDIA, AMD}, for CPUs it is {AMD, Intel}. A product whose
  brand isn't in its category's pair gets no matchup.
- **P qualifies** when it has a main-metric score and a price today. P can be in any tier.
- **A candidate qualifies** when all of these hold:
  - it is the other brand of the pair;
  - its tier is `current` or `current-1`;
  - it has a main-metric score;
  - it has a price today (in stock);
  - `|score(C) - score(P)| / score(P) <= 0.15`.
- **Pick:** the qualifying candidate with the smallest score gap. If another qualifying candidate's
  gap is within **3 points** of the best one's, has the same VRAM as P, and the best one doesn't,
  that candidate wins instead. CPUs skip the VRAM tie-break. Any tie left over goes to the lower
  price, then the lower product id, so the pick is deterministic.
- **No qualifying candidate** means no panel.

"Price today" is `getValueRows`' price: the cheapest latest in-stock listing price on the latest
snapshot date. That is the same rule /value, /products and /compare use (#59).

## 3. The sentence
Cost per point is `price / score`. For each metric where **both** sides have a score:
`r = cost(P) / cost(R)`.

- `r < 0.98` → "**{P} is N% cheaper per frame** than {R} at {metric label}", with `N = round((1 - r) * 100)`.
- `r > 1.02` → "**{P} costs N% more per frame** than {R} at {metric label}", with `N = round((r - 1) * 100)`.
- otherwise → "**About the same cost per frame** as {R} at {metric label}".

The main metric always gets a sentence. Ray tracing (GPUs only) gets its own sentence when both
sides have an RT score, and is left out otherwise. If the two sentences point different ways (P
cheaper on raster, dearer on RT), both are shown as they are. Nothing combines them.

Under the sentences: each side's price and Perf/A$1k (`perfPerKilo`) for the main metric, set in
mono like every other price.

## 4. UI
- `MatchupPanel.svelte` sits on the product page directly after the buy signals.
- The heading is "Head to head", with "vs {rival display name}" linking to `/product/{id}`.
- It shows the sentence(s) from §3 and the price + Perf/A$1k line.
- A "Compare side by side" link goes to `/compare?ids={P},{R}`.
- Source line: `sourceCitation(metric)` linked to `source_url`, and the as-of date, matching
  /products and /value.
- Lucide icons only, no emojis, the existing card styling, and the visual-refresh type scale (#22).
- Display names come from `buildDisplayNames`, so a base card carries its VRAM where a sibling
  exists.

## 5. Code
- **`web/src/lib/matchups.ts`** (pure, client-safe, unit tested):
  - `findRival(p, candidates, category)` returns the rival or null;
  - `matchupLines(p, rival, category)` returns the sentence data per metric (direction, N, metric
    key) for the component to render.
- **Server:** `getValueRows` gains a `brand` field (it's already in `products`). The product page
  loader calls it for the product's category (it's memoised per category), attaches perf scores
  with `perfFor`, and returns `matchup: { rival, lines } | null`. The loader builds nothing else.
- **No DB schema, pipeline or migration changes.** The perf data stays in `db/perf_index.json`.
- Every file stays under the 350-line cap (`test/boundaries.test.ts`).

## 6. Testing
- **Vitest (`matchups.test.ts`):**
  - brand pairs, including Intel GPUs excluded both ways;
  - the 15% boundary (exactly 15% qualifies, just over it doesn't);
  - the tier filter;
  - out of stock on either side;
  - a missing score on either side;
  - the VRAM tie-break inside and outside the 3-point window;
  - the deterministic tie on price and id;
  - the 0.98/1.02 thresholds and rounding;
  - RT left out when one side lacks it;
  - CPUs skipping the VRAM tie-break.
- **Loader test:** a matchup is returned for a seeded pair, and null for a product without one.
- **Playwright:** the seeded DB gets one NVIDIA/AMD pair that matches and one product with no
  rival. The test checks the panel's text, the rival link and the compare link, and that the
  no-rival page has no panel. The product page joins the axe sweep in light and dark, and the
  panel is checked at 320px.

## 7. Out of scope
- Curated pairs and any override file. Add one later only if the automatic picks prove wrong in
  practice.
- Intel GPU matchups.
- More than one rival per page.
- Matchups on /compare or /value.
- Alerts or Discord messages about matchups.

## 8. Deploy
There are no data, schema or pipeline changes. Merge, then run `deploy/redeploy.sh` outside
04:00–09:59. Add a CHANGELOG line under Unreleased; this is a feature, so the next release is 0.7.0.
