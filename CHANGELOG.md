# Changelog

Every Trackaroo release, newest first. The site shows this at `/changelog`, and the
footer links to it from the running version.

How it works:
- Each change adds a line under **Unreleased** in the same PR.
- To cut a release, run `python release.py X.Y.Z` from the repo root. It moves Unreleased into a dated release and bumps `web/package.json` and its lockfile.
- Commit the result. After merging, tag the merge commit `vX.Y.Z`.
- Versions: the minor number goes up for features, the patch number for fixes.

## Unreleased

- A part added to the watchlist now leaves Discover's Requested list as soon as it is deployed, instead of at the next morning's run (#90).
- Now tracking the Radeon RX 9050 8GB (requested from the Discover page).
- Retired 23 parts that retailers no longer sell: Arc A770, Core Ultra 5 245, eleven Core 13th/14th-gen models, nine GeForce RTX 30/40 cards and the Radeon RX 6600. Their pages and price history stay.
- Now tracking seven parts requested from the Discover page: Core Ultra 7 270K Plus, GeForce RTX 5050 8GB, Radeon RX 6500 XT 4GB, Ryzen 5 8500G, Ryzen 7 8700G, Ryzen 7 9850X3D and Ryzen 9 5900XT.
- `deploy/redeploy.sh` now applies watchlist changes itself, including retirements and rollovers that change more than 5 parts. Before, those were refused on boot and needed a separate `seed.py --allow-bulk` on the server.

## 0.9.0 — 2026-10-06

- Product generations now come from one config file (db/generations.toml); retiring a product is a status in the watchlist instead of a code change (#17, #18).
- The Discover page lists tracked parts no retailer has sold for 30 days, to retire or keep.
- A new `manage_watchlist.py` command handles generation launches and retirements (rollover, add, retire, check, reassign) instead of hand-editing files (#19).
- Fixed: buttons that submit a form (Track / Ignore / Retire / Keep on Discover, price alerts) were refused with "Cross-site POST form submissions are forbidden" on the plain-http server.

## 0.8.0 — 2026-10-05

- Prices on /products, /compare, /value and Head to head now skip a listing its retailer has not shown for more than 7 days, the same rule the product page headline already used, so every page agrees on a product's price (#70).
- Only one daily run can happen at a time: a second run started while one is going exits straight away instead of scraping twice. Python dependencies are now pinned by hash, with test-only packages split out of the image (#15).
- Watchlist upkeep: the unused search-alias column is gone (matching uses chip keys), Ryzen 10000 parts get spec pages, Intel spec sources are configurable, and a part added this week shows as pending specs instead of a gap (#20).
- If PC Case Gear changes its search key, the PCCG scraper now finds the new key on PCCG's own site and carries on, instead of stopping until someone updates it by hand (#11).
- When the database is missing or out of date, the error page now says so and shows how to fix it, instead of a bare "Internal Error" (#29).

## 0.7.0 — 2026-10-04

### Added
- Head to head on product pages (#60): how a GPU or CPU's cost per frame in AU today compares with its closest rival from the other brand (NVIDIA vs AMD, AMD vs Intel), with ray tracing shown separately and the performance source cited.

### Fixed
- A price alert can only be deleted from its own product page, and a target price is rounded to cents and capped at $100,000 (#15).

### Changed
- Behind the scenes: the price chart, the GPU/CPU list and its filters are split into smaller pieces, with no visible change (#61).

## 0.6.1 — 2026-10-04

### Fixed
- Prices inside buy-signal sentences now use the same mono number face as every other price (#62).
- The self-hosted fonts are cached by the browser for a year instead of being re-checked on every page load (#63).
- /value now prices products by the same rule as /products and /compare (each listing's latest in-stock price), so a Perf/A$1k figure is the same on every page (#59).

## 0.6.0 — 2026-10-03

### Added
- Price to performance (#33): a Perf / A$1k column on the GPU and CPU lists and /compare, and a /value page with price against performance, the value frontier and the best buy under $400, $700, $1,000, $1,500 and $2,500. Performance is published TechPowerUp relative performance, with its source on hover; parts the source does not list show "–".

## 0.5.0 — 2026-10-03

### Added
- OzBargain deals on product pages and /deals, with a Discord alert when a deal beats our best in-stock price (#34).

### Changed
- Visual refresh (#22): new type scale and fonts (self-hosted), terminal wordmark and icons, a shared page header on every page, wider table pages, mono prices, a segmented 90-day range bar on catalogue rows, and no empty homepage columns.

## 0.4.0 — 2026-10-03

### Added
- **Buying signals** on every product (#31): an "Is now a good time to buy?" checklist with icons and the evidence for each badge (price percentile, lowest in N days, vs 30-day average, 7-day trend, upcoming AU sale events, successor announced), plus a 30 / 90 / 180-day low / median / high table.
- **US launch MSRP in today's AUD** (#32): "N% under/over US launch MSRP (≈A$X inc. GST)" on the product page, a sortable "vs MSRP" column in the catalogue, and a "Below MSRP" filter on /deals. The rate is cached daily from the RBA, with the ECB rate (via Frankfurter) as a fallback.
- AU sale events (EOFY, Prime Day, Click Frenzy, Singles Day, Black Friday, Boxing Day) marked on the price chart.
- The release number in the footer, linking to this page.

### Changed
- Icons now come from Lucide. The arrow on Buy links is an icon, and a test keeps emoji out of the web app.

## 0.3.0 — 2026-10-02

Everything up to the 2-Oct deploy (build `328073f`), recorded as one release when versioning started.

- Correct prices: GPU memory variants are separate products, and the deal floor is 2% and $10.
- Faster pages (gzip, smaller payloads) and a sturdier pipeline: retry window, run bookkeeping, `/healthz`, backups and a restore drill.
- UI and UX pass: catalogue filters and sort in the URL, compare, chart averages, accessible light and dark themes.
- Deployment with docker compose and `deploy/redeploy.sh`.
- New-part discovery: the `/discover` page and a Discord notice (#16).
- Retailer views show the buyable price, not a cheaper sold-out one (#23).
