# Changelog

Every Trackaroo release, newest first. The site shows this at `/changelog`, and the
footer links to it from the running version.

How it works:
- Each change adds a line under **Unreleased** in the same PR.
- To cut a release, run `python release.py X.Y.Z` from the repo root. It moves Unreleased into a dated release and bumps `web/package.json`.
- Commit the result. After merging, tag the merge commit `vX.Y.Z`.
- Versions: the minor number goes up for features, the patch number for fixes.

## Unreleased

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
