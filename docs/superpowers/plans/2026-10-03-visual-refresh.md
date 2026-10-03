# Visual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the signed-off style tile across the dashboard:
- self-hosted display, sans and mono fonts, a type scale and three surface levels;
- the terminal wordmark and matching icons;
- one `PageHeader` on every route, and wider table pages;
- the segmented 90-day range bar on the product page and on catalogue rows;
- mono prices, larger controls, and no empty homepage columns.

**Architecture:**
- **Tokens** live in `web/src/app.css` as CSS variables, exposed to Tailwind v4 through `@theme`.
- **New components:** `Wordmark` and `PageHeader`. `PriceRangeBar` is restyled.
- **Data:** a single memoised grouped query adds `range90` to catalogue rows.
- No schema, pipeline or data change.

**Tech Stack:** SvelteKit 2 / Svelte 5, Tailwind v4, TypeScript, better-sqlite3, vitest, Playwright + axe.

**Spec:** `docs/superpowers/specs/2026-10-03-visual-refresh-design.md`. Style tile: https://claude.ai/artifact/QpYub9ooWaaaM4JMJnJaqX (the dark and light hex values below are copied from it).

## Global Constraints

- **Fonts:** self-hosted woff2 in `web/static/fonts/`, latin subset:
  - Bricolage Grotesque 700 and 800;
  - IBM Plex Sans 400, 500 and 600;
  - IBM Plex Mono 500 and 600;
  - each family's OFL licence file alongside.

  No request to `fonts.googleapis.com` or `fonts.gstatic.com`. No new npm dependency.
- **Type scale:**

  | Token | Size / line height | Face | Weight | Other |
  |---|---|---|---|---|
  | display | 32/38 | display | 800 | -0.02em |
  | title | 20/28 | display | 700 | |
  | section | 12/16 | sans | 600 | uppercase, 0.12em, muted |
  | body | 14/20 | sans | | |
  | meta | 12/16 | sans | | muted |
  | price | 22/28 | mono | 600 | tabular |
- **Surfaces:**

  | Token | Dark | Light |
  |---|---|---|
  | `--surface-2` | #1c2030 | #f9fafb |
  | `--surface-3` | #232838 | #f1f3f6 |
  | `--border-card` | #2c3244 | #d5dae2 |
  | `--shadow-card` | none | `0 1px 2px rgba(16,24,40,0.06)` |
- Every existing colour token keeps its exact value.
- **Wordmark:** mono `trackaroo` plus `_` in `--accent`, with the accessible name "Trackaroo home".
- **Widths:** table pages (/products, /deals, /movers, /discover) use `max-w-7xl` through a `wide: true` loader flag. All other pages keep `max-w-6xl`. Header and footer follow the same width.
- **Controls:** chips, buttons and SegmentedControl have a minimum height of 28 px, badges 24 px, and text of at least 12 px.
- **Segmented bar:** 6 equal segments. Segments 1–2 use `--down`, 3–4 use `--accent`, and 5–6 use `--up` when filled; unfilled segments use `--border-strong`. The visible text label is always present.
- **General rules:**
  - No emojis in `web/src` (`noEmoji.test.ts`). Icons come from `@lucide/svelte`, per file and aria-hidden.
  - Use the `$lib/formats` helpers and never `toLocale*`.
  - Client code never imports `$lib/server`. Files stay at or under 350 lines.
  - e2e uses `goto()` and seeded data only.
  - `contrast.test.ts`, axe (both themes) and `mobile.spec.ts` (320 and 390 px) stay green.
- Never open `db/trackaroo.db`.
- **Gate:** after every task, `python -m pytest -q`, then from `web/`: `npm run check` 0/0, `npm test` and `npm run test:e2e`.

## Review Focus

1. **Font loading fails or is slow:** text must render immediately in the fallback stack (`font-display: swap`) with no layout break. Prices must stay tabular in the fallback mono. Task 1 tests that the CSS declares swap and keeps the fallback stacks.
2. **A long product name or title in PageHeader at 320 px:** it wraps, without horizontal overflow, and actions drop below. Task 3 adds a mobile e2e case with the longest seeded product name.
3. **A product with no 90-day history, or a flat price (low = high):** the row shows no bar, or the existing "steady" wording, never a NaN segment. Task 4 tests both.
4. **Light theme:** the new surfaces, card border and shadow keep text AA and do not wash out. Task 1 adds the contrast pairs, and axe runs in both themes.
5. **Exactly one h1 per page** after PageHeader replaces the hand-built headings, including the product page, whose headline also had one. Task 3 asserts this on every route.

## File Structure

| File | Responsibility |
|---|---|
| `web/static/fonts/*` (new) | woff2 and OFL licences |
| `web/src/app.css` | @font-face, font, type and surface tokens, `.num` |
| `web/src/lib/components/Wordmark.svelte` (new), `Header.svelte` | Identity |
| `web/static/favicon.svg`, `icon-*.png`, `apple-touch-icon.png`, `web/scripts/render-icons.mjs` (new) | Icons |
| `web/src/lib/components/PageHeader.svelte` (new), every `routes/**/+page.svelte`, `+error.svelte`, `+layout.svelte`, table-page loaders | Chrome and widths |
| `web/src/lib/components/PriceRangeBar.svelte`, `ProductRow.svelte`, `web/src/lib/server/queries/catalog.ts` (or a new `queries/range.ts` if catalog.ts would pass 350 lines), `web/src/lib/models.ts` | Signature bar |
| `Chip`, `Badge`, `SegmentedControl` and button styles, `CategorySection.svelte`, price displays | Density, prices and the homepage |
| `web/test/*.test.ts`, `web/e2e/*.spec.ts` | Tests |

---

### Task 1: Foundations — fonts, type scale, surfaces

**Files:**
- Create: `web/static/fonts/` (woff2 and licences), `web/test/fonts.test.ts`
- Modify: `web/src/app.css`, `web/test/contrast.test.ts`

- [ ] **Step 1: Fetch fonts.** Download the latin woff2 files once from jsDelivr's @fontsource packages, with `curl -fL -o`:
  - `https://cdn.jsdelivr.net/npm/@fontsource/bricolage-grotesque/files/bricolage-grotesque-latin-700-normal.woff2` (and 800);
  - `https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-{400,500,600}-normal.woff2`;
  - `https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-{500,600}-normal.woff2`;
  - each package's `LICENSE` file, saved as `web/static/fonts/<family>-OFL.txt`.

  Check each woff2 starts with the bytes `wOF2`. If a URL 404s, look up the package's `files/` listing on jsDelivr and record the real names in the report.
- [ ] **Step 2: Failing tests.**
  - **`fonts.test.ts`:**
    - no `fonts.googleapis.com` or `fonts.gstatic.com` string anywhere under `web/src` or `web/static`;
    - `app.css` declares an `@font-face` for each of the 7 files, with `src: url('/fonts/<file>') format('woff2')` and `font-display: swap`;
    - each referenced file exists in `web/static/fonts`;
    - `--font-sans` and `--font-mono` still end with the current fallback stacks.
  - **`contrast.test.ts`, new pairs in both themes:**
    - text and text-muted on surface-2 and surface-3 must reach at least 4.5:1;
    - border-card against bg must reach at least 1.5:1.
- [ ] **Step 3: Run** `npm test` and expect FAIL.
- [ ] **Step 4: Implement in `app.css`:**
  - the `@font-face` blocks;
  - `--font-sans: 'IBM Plex Sans', <existing stack>` and `--font-mono: 'IBM Plex Mono', <existing stack>`;
  - the new `--font-display: 'Bricolage Grotesque', var(--font-sans)`;
  - the surface tokens in `:root` and `[data-theme='light']`, with the exact values from Global Constraints;
  - in `@theme inline`: `--color-surface-2`, `--color-surface-3`, `--color-border-card`, `--font-display`, `--shadow-card`, and the text sizes as `--text-display: 2rem; --text-display--line-height: 2.375rem` and so on for title (1.25rem/1.75rem), section (0.75rem/1rem), body (0.875rem/1.25rem), meta (0.75rem/1rem) and price (1.375rem/1.75rem);
  - small utility classes for the tracking and weight that tokens cannot carry: `.text-display` adds `font-family: var(--font-display); font-weight: 800; letter-spacing: -0.02em`; `.text-title` is the display face at 700; `.text-section` is uppercase, `0.12em`, 600, muted; `.text-price` is mono, 600, tabular-nums.

  Check that Tailwind v4 lets a utility class share a name with a theme text token. If it doesn't, name the classes `.type-display` and so on, and say so in the report.
  - `.num` keeps `font-variant-numeric: tabular-nums` and now uses `font-family: var(--font-mono)`.
- [ ] **Step 5: Run** the full gate.
  - Some visual e2e assertions may depend on text width. Fix only genuine regressions; never weaken an assertion.
  - Take a 1440 px dark screenshot of `/` into the system temp dir to confirm the fonts load. Check that the network panel shows `/fonts/...` with 200.
- [ ] **Step 6: Commit**: `feat(web): self-hosted Bricolage/IBM Plex fonts, type scale and surface tokens (#22)`.

---

### Task 2: Identity — wordmark and icons

**Files:**
- Create: `web/src/lib/components/Wordmark.svelte`, `web/scripts/render-icons.mjs`, `web/test/wordmark.test.ts`
- Modify: `web/src/lib/components/Header.svelte`, `web/static/favicon.svg`, `web/static/icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png`, `web/src/routes/+error.svelte`

**Interfaces:**
- Produces: `<Wordmark size?: 'header' | 'large' />`.
  - It renders `<a href="/" aria-label="Trackaroo home" class="...">trackaroo<span class="text-accent" aria-hidden="true">_</span></a>` in the mono face at weight 600.
  - Sizes: 18 px (header) and 28 px (large).

- [ ] **Step 1: Failing tests** (`wordmark.test.ts`, component mount like the other component tests):
  - the link has the accessible name "Trackaroo home" and href `/`;
  - its text is `trackaroo_`;
  - the `_` carries the accent class.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - Replace the dot-plus-text in `Header.svelte` with `<Wordmark />`. Keep the existing e2e that clicks home, and update its locator to the accessible name if it used the old text.
  - Use the large wordmark on `+error.svelte` above the heading.
  - **Favicon:** rewrite `static/favicon.svg` (viewBox 0 0 64 64) as a `#2563eb` rounded square (rx 14). On it, a white `t` drawn as two paths: a vertical stem with a hooked foot and a crossbar, centred-left at about 60% of the height. Beside it, a white `_` bar (`rect`) at the baseline. No `<text>`, so no runtime font.
  - **`render-icons.mjs`:** use `@playwright/test`'s `chromium` (already a dev dependency) to render the SVG at 192, 512 and 180 (apple-touch), and a 512 maskable version with the mark scaled to 80% inside a full-bleed `#2563eb` background. Write the PNGs over the existing files. Run it once and commit the PNGs. Document `node scripts/render-icons.mjs` in a comment at the top of the script.
- [ ] **Step 4: Run** the full gate. Open the 192 PNG with the Read tool and describe it in the report.
- [ ] **Step 5: Commit**: `feat(web): terminal wordmark and matching t_ icons (#22)`.

---

### Task 3: PageHeader on every route, wider table pages

**Files:**
- Create: `web/src/lib/components/PageHeader.svelte`, `web/test/pageHeader.test.ts`
- Modify:
  - `web/src/routes/+layout.svelte` and `Header.svelte` (width);
  - each `+page.svelte` under `routes/` (home, products, product/[id], deals, movers, discover, compare, changelog), and `+error.svelte`;
  - the loaders of /products, /deals, /movers and /discover (return `wide: true`);
  - `web/e2e/app.spec.ts` and `web/e2e/mobile.spec.ts`.

**Interfaces:**
- Produces:
```ts
// PageHeader.svelte props
{ title: string; subtitle?: string | null; crumbs?: Crumb[] /* existing Breadcrumbs type */; compact?: boolean; actions?: Snippet }
```
- It renders `<header data-testid="page-header">`, then Breadcrumbs (when crumbs are given), then an `<h1 class="text-display">` (or `text-title` when compact), then a subtitle `<p class="text-body text-text-muted">`, then the actions.
  - On md and up, the actions sit right-aligned in a flex row with the title block. On phones they wrap below.
  - It closes with a bottom border and `pb-4 mb-6`.

- [ ] **Step 1: Failing tests.**
  - **vitest:** the title renders as the only h1; the subtitle, crumbs and actions snippet render; compact uses `text-title`.
  - **e2e:** for each of `/`, `/products?category=gpu`, `/product/<seeded id>`, `/deals`, `/movers`, `/discover`, `/compare`, `/changelog` and a 404 path, assert:
    - exactly one `h1` on the page;
    - that h1 is inside `[data-testid="page-header"]`.
  - **e2e:** /products and /deals `<main>` has a computed max-width of 80rem (`max-w-7xl`), and /changelog's is 72rem.
  - **mobile.spec:** the product page with the longest seeded model name has no horizontal overflow at 320 px.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - Replace each route's hand-built heading block with PageHeader, keeping the existing subtitle and count text.
  - Product page: PageHeader carries the product name, with crumbs. `ProductHeadline` keeps the price, MSRP line and buy info, but no longer renders its own h1. Check `ProductHeadline.svelte`'s heading and remove the duplicate.
  - Layout: `const wide = $derived((page.data as { wide?: boolean }).wide === true)`. `<main>` gets `max-w-7xl` when wide, else `max-w-6xl`. Header and footer inner containers use the same width class (pass it to Header as a prop).
  - Remove /discover's inner `mx-auto max-w-5xl px-4 py-6` wrapper, keeping its `space-y-8`.
  - Keep every existing e2e heading assertion meaningful, updating selectors only where the markup changed.
- [ ] **Step 4: Run** the full gate.
- [ ] **Step 5: Commit**: `feat(web): shared PageHeader on every route, wider table pages (#22)`.

---

### Task 4: Signature segmented range bar on the product page and rows

**Files:**
- Modify: `web/src/lib/components/PriceRangeBar.svelte`, `web/src/lib/components/ProductRow.svelte`, `web/src/lib/models.ts`, the products loader, `web/src/lib/server/queries/catalog.ts` (or new `queries/range.ts` exported via the `repos.ts` barrel), `web/test/*` (component and loader tests), `web/e2e/app.spec.ts`

**Interfaces:**
- Produces:
```ts
export const RANGE_SEGMENTS = 6;
export function filledSegment(position: number | null): number | null // 0..5, position in [0,1] -> Math.min(5, Math.floor(position * 6)); null -> null
// catalogue rows gain
range90: { low: number; high: number } | null
// server
export function getRange90(db: DB, productIds?: number[]): Map<number, { low: number; high: number }>
```
- `getRange90` takes the min and max over the last 90 days of the daily cheapest in-stock, non-bundle, active-listing price. Reuse the `dailyCheapestInStock` / `notBundle` fragments in `queries/sql.ts` and window on the global latest `snapshot_date` minus 89 days. It runs as one grouped query, memoised with `memo(db, 'range90', ...)`.

- [ ] **Step 1: Failing tests.**
  - **`filledSegment`:** 0 gives 0, 0.49 gives 2, 0.5 gives 3, 1 gives 5, null gives null.
  - **PriceRangeBar component:** 6 segments render; the filled one carries the down/accent/up class by index; the label text stays; flat range or null position keeps the existing wording with no filled segment; the aria-label is unchanged.
  - **`getRange90`** (in-memory DB from schema.sql):
    - only in-stock, active, non-bundle listings count;
    - only the last 90 days count, and older data is excluded;
    - a product with no history is absent from the map;
    - low = high is allowed.
  - **Loader:** catalogue rows carry `range90`, null when absent.
  - **e2e:** on `/products?category=gpu` at 1440 px, a seeded product with history shows a row bar with 6 segments and the visible text label.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - **PriceRangeBar:** restyle it as a flex row of 6 rounded segments (h 6 px, gap 2 px), with a `size: 'full' | 'compact'` prop. Compact is 96 px wide with an 11 px label underneath. Keep the existing label logic. The position is computed from `(current - low) / (high - low)`, as today.
  - **ProductRow:** shown from the lg breakpoint up when `range90` exists and the row's shown price is not null. Compute the position against the row's shown price, clamped to [0, 1]. When high equals low, use the existing steady wording.
  - Measure the `/products` `__data.json` size before and after, and record both in the report. It must grow by less than 10%.
- [ ] **Step 4: Run** the full gate.
- [ ] **Step 5: Commit**: `feat(web): segmented 90-day range bar on the product page and catalogue rows (#22)`.

---

### Task 5: Mono prices, control sizes, no empty homepage columns

**Files:**
- Modify: `Chip.svelte`, `Badge.svelte`, `SegmentedControl.svelte`, `StockBadge.svelte`, `CategorySection.svelte`, price displays (`ProductHeadline`, `ProductRow`, `OfferRow`, `MoverRow`, `PriceChange`, deals and compare pages, `OzbDealsPanel`), card containers (`CategorySection`, `BuyPanel`, `OzbDealsPanel`, `SpecPanel`, the PriceChart wrapper), `web/e2e/app.spec.ts`, `web/e2e/seed.mjs` (only if needed for an empty-column case)

- [ ] **Step 1: Failing tests.**
  - **e2e homepage:** when the CPU section has no rises (check the seed; if the seed has rises, add or adjust a fixture so one column is empty), `[data-testid="biggest-rises"]` for that section is absent, and the text "No big price rises this week." is visible in it.
  - **vitest:**
    - Chip, Badge and SegmentedControl render with a min-height class (28 px for chips and buttons, 24 px for badges) and text of at least 12 px;
    - a scan of `web/src` finds every element showing a formatted AUD price (`formatAud(`) with `.num` or `text-price` on it or its parent, listing offenders. If that is too brittle, assert the named components instead, and say which in the report.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.** **Load the `frontend-design` skill first** and match the style tile.
  - Apply `.num` or `text-price` to all prices.
  - Apply min heights and sizes to the controls.
  - Card containers use `bg-surface border border-border-card shadow-card rounded-xl`; popovers and the command palette use `bg-surface-3`.
  - **Homepage:** for each movers column with zero rows, do not render the column. Show a one-line muted message in the section (the drops wording mirrors the rises one), and let the remaining columns span the width.
- [ ] **Step 4: Run** the full gate, including axe in both themes and `mobile.spec.ts`.
- [ ] **Step 5: Commit**: `feat(web): mono prices, larger controls, card surfaces, no empty homepage columns (#22)`.

---

### Task 6: Screenshots, docs and gate

- [ ] **Before screenshots.** Create a git worktree of `main` at the branch point (`git worktree add <tmp> e27c5ad`, `npm ci` there), and serve its seeded e2e dev server on another port by pointing `TRACKAROO_DB` at a scratch copy of the e2e DB. Never use `db/trackaroo.db`.

  Screenshot `/`, `/products?category=gpu`, a product page and `/deals` at 390 and 1440 px, dark and light, into the system temp dir. Remove the worktree afterwards.
- [ ] **After screenshots:** the same set on this branch.
- [ ] **Docs:**
  - README "Frontend": a short "Design system" note covering the fonts and where they live, the type and surface tokens, PageHeader, Wordmark, `render-icons.mjs`, and that fonts are self-hosted.
  - `CLAUDE.md`: test counts.
  - `docs/ARCHITECTURE.md` decision log: "Visual refresh: polish + signature; terminal wordmark; self-hosted fonts".
  - `CHANGELOG.md`: a line under `## Unreleased` → `### Changed`.
  - `STATUS.md`: a dated bullet.
- [ ] **Full gate:** pytest, check 0/0, vitest, Playwright and `npm run build`. List the screenshot paths in the report, before and after, by page, width and theme. Commit: `docs: visual refresh (#22)`.
