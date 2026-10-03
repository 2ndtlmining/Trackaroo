# Visual refresh: design

**Date:** 2026-10-03 · **Issue:** #22 · **Sub-project 5 of 6**
**Status:** direction and style tile signed off by the owner on 3-Oct-2026 (style tile: https://claude.ai/artifact/QpYub9ooWaaaM4JMJnJaqX). Awaiting written-spec review.

## 1. Purpose
Make Trackaroo look like a polished, trustworthy price tool rather than a developer dashboard. The settled decisions stay as they are: the dark default, CSS-variable tokens, one restrained accent in charts, the health-first homepage and the search-first /products.

### Owner decisions (3-Oct-2026)
- **Direction "Polish + signature"** (issue option A, plus B touches). Keep the current system, and add:
  - a type scale and a display face;
  - deeper surfaces;
  - a shared page header and wider table pages;
  - mono tabular prices;
  - the **segmented range bar** as the signature element.
- **Wordmark C, "Terminal":** mono lowercase `trackaroo`, followed by an accent-coloured `_`.
- **The style tile is signed off** as the basis for page work: its fonts, type scale, surfaces and components.

### Success criteria
- The header shows the terminal wordmark, and the favicon and app icons match it.
- Every route uses one `PageHeader`.
- Every price uses the mono tabular face.
- Table pages use the wider layout.
- Catalogue rows show the segmented 90-day range bar.
- No empty homepage column is rendered.
- The three fonts are self-hosted. No request leaves for Google or any other font host.
- These stay green in both themes: `contrast.test.ts` (with the new pairs), axe, and `mobile.spec.ts` (no overflow at 320 and 390 px).
- The PR carries before/after screenshots at 390 and 1440 px in both themes.

## 2. Out of scope
- New colours for meanings. All existing colour tokens keep their values; only surfaces are added.
- A component library.
- A `/styleguide` route. The signed-off style tile replaces it.
- Chart restyling beyond fonts.
- Price-to-performance (#33).

## 3. Foundations (`web/src/app.css`)
- **Fonts.** These woff2 files are self-hosted under `web/static/fonts/`:
  - Bricolage Grotesque 700 and 800;
  - IBM Plex Sans 400, 500 and 600;
  - IBM Plex Mono 500 and 600;

  each with its OFL licence file. They are declared with `@font-face` (`font-display: swap`), latin subset only.
  - `--font-sans` becomes `'IBM Plex Sans', <the current system stack>`.
  - `--font-mono` becomes `'IBM Plex Mono', <the current mono stack>`.
  - The new `--font-display` is `'Bricolage Grotesque', var(--font-sans)`.
  - Files are fetched once at development time from the @fontsource packages on jsDelivr and committed. No npm dependency is added.
- **Type scale.** The tokens below are exposed as Tailwind `@theme` text sizes (`text-display`, `text-title`, `text-section`, `text-body`, `text-meta`, `text-price`):

  | Token | Size / line height | Face | Weight | Other |
  |---|---|---|---|---|
  | display | 32/38 | display face | 800 | tracking -0.02em |
  | title | 20/28 | display face | 700 | |
  | section | 12/16 | sans | 600 | uppercase, tracking 0.12em, muted |
  | body | 14/20 | sans | | |
  | meta | 12/16 | sans | | muted |
  | price | 22/28 | mono | 600 | tabular-nums |

  The existing `.num` class switches to the mono face and keeps tabular-nums.
- **Surfaces.**

  | Token | Dark | Light |
  |---|---|---|
  | `--surface-2` | #1c2030 | #f9fafb |
  | `--surface-3` | #232838 | #f1f3f6 |
  | `--border-card` | #2c3244 | #d5dae2 |
  | `--shadow-card` | `none` | `0 1px 2px rgba(16,24,40,0.06)` |

  Each is exposed as a Tailwind colour. Cards use `bg-surface border-border-card shadow-card`; raised panels and popovers use surface-2 and surface-3.
- **Unchanged.** Every colour token keeps its value. `contrast.test.ts` gains the new pairs, which must each pass:
  - text and text-muted on surface-2 and surface-3, at 4.5:1;
  - border-card against bg, at 1.5:1 as a decorative boundary. Input boundaries keep the existing `--border-input` 3:1 rule.

## 4. Identity
- **`Wordmark.svelte`.** A link to `/` with the accessible name "Trackaroo home". Its content is `trackaroo` in the mono face, weight 600, followed by `_` in `--accent`. There are two sizes: header (18 px) and large (28 px, used on the error page). It replaces the dot-plus-text in `Header.svelte`.
- **Favicon and app icons.** `static/favicon.svg` becomes the `t_` mark: a mono `t` and an accent `_` in white on an `#2563eb` rounded square. It is drawn as paths, so no font is needed at runtime.
  - `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` (with a safe zone) and `apple-touch-icon.png` are rendered from that SVG once, using Playwright in a dev script (`web/scripts/render-icons.mjs`), and committed.
  - `manifest.webmanifest` and the theme-color are unchanged.

## 5. Shared chrome
- **`PageHeader.svelte`** takes these props:
  - `title` (string);
  - `subtitle?` (string);
  - `crumbs?` (the existing Breadcrumbs input);
  - an `actions?` snippet.

  Layout:
  - The breadcrumb sits above an `h1` set in `text-display` (or `text-title` when `compact`). The subtitle is in `text-body` muted.
  - Actions align to the right on md and up, and wrap below on phones.
  - A bottom border in `border-border` sits 18 px below.

  It replaces every route's hand-built heading: home, products, product, deals, movers, discover, compare, changelog, and the error page (compact). The product page keeps its own headline data (price, MSRP line) below the PageHeader title.
- **Widths.** `<main>` keeps `max-w-6xl` for reading pages. Table pages (/products, /deals, /movers, /discover) widen to `max-w-7xl`: the layout reads a per-route flag (`page.data.wide` returned by those loaders), not a nested wrapper. /discover's inner `mx-auto max-w-5xl px-4 py-6` wrapper is removed. Header and footer align to the same width as `<main>`.

## 6. Signature and density
- **Segmented range bar.** `PriceRangeBar.svelte` is restyled as 6 equal segments.
  - The segment holding today's position is filled. Segments 1–2 (near the low) use `--down`, segments 5–6 (near the high) use `--up`, and the middle segments use `--accent`. Unfilled segments use `--border-strong`.
  - Its existing text (`near its 90-day low`, or the current wording) stays visible, so colour is never the only signal. Its `aria-label` is unchanged.
- **Rows get the bar.** Catalogue rows (`ProductRow.svelte`, lg and up) show a compact bar (96 px wide) from a 90-day low/high per product. The products loader adds one grouped query, the min and max of the daily cheapest in-stock price over the last 90 days. It is memoised with the existing `memo(db, …)` and adds `range90: { low, high } | null` to catalogue rows. There is no per-product query, and payload growth is at most two numbers per row.
- **Prices.** Every price display uses the mono tabular face via `.num` or `text-price`: headline, rows, offers, deals, movers, compare and the OzBargain panel.
- **Controls.** Chip, Badge, SegmentedControl and buttons get a minimum height of 28 px (badges 24 px) and a text size of at least 12 px. Existing 44 px touch rules on phones stay.
- **Homepage.** When a section's column (e.g. "Biggest rises (7d)") has no rows, that column is not rendered. One muted line, "No big price rises this week.", replaces it, and the remaining columns take the width.

## 7. Testing
- **vitest:**
  - `contrast.test.ts` covers the new pairs;
  - Wordmark: accessible name and the accent `_`;
  - PageHeader: renders title, subtitle, crumbs and actions; h1 count is 1;
  - PriceRangeBar: filled segment index for positions 0, 0.5 and 1, null position, and label text;
  - the range90 query, on a seeded in-memory DB: low/high over 90 days and in-stock only, null without history;
  - a font guard: no `fonts.googleapis.com` or `fonts.gstatic.com` anywhere in `web/src` or `web/static`, and every `@font-face` url points at `/fonts/`.
- **Playwright:**
  - every route has exactly one h1, inside `[data-testid="page-header"]`;
  - the header shows the wordmark link "Trackaroo home";
  - the homepage renders no empty movers column (seeded case);
  - `mobile.spec.ts` stays green;
  - axe stays green in both themes.
- **Screenshots:** before (main at the branch point) and after, at 390 and 1440 px, dark and light, for home, /products?category=gpu, a product page and /deals. They go to the system temp dir, are listed in the PR, and are not committed.

## 8. Deploy
Merge, then run `deploy/redeploy.sh` outside 04:00–09:59. There is no data or schema change. Add a CHANGELOG line under Unreleased.
