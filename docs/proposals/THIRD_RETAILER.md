# Adding a Third Retailer — Feasibility & Scope

**Status:** proposal, not started. Probed 30-Aug-2026.

Candidates considered: **Mwave, Umart, Centre Com, PLE.**

## Recommendation

**Build Mwave first, and only Mwave.** It is the largest of the four, it is the
only one already permitted by the database schema, and it probed as a
conventional server-rendered scrape of the same shape as Scorptec. Add a second
retailer only once Mwave has run clean for a fortnight.

**Rule out Centre Com.** Not a scope decision — a technical one. See below.

## The cost is not the scraper

Writing `scraper/mwave.py` is the *small* half. The retailer name is hardcoded
in at least nine places, and every one must be updated or the new data is
silently dropped or rejected:

| Where | What it does | Breaks how |
|---|---|---|
| `db/schema.sql:37` | `CHECK (retailer IN ('scorptec','pccg','mwave'))` | INSERT rejected outright |
| `ingest.py:37` | `_SNAPSHOT_FILENAME_RE` only matches `scorptec\|pccg` | Snapshot file silently skipped |
| `health_checks.py:89,229,323` | expected-retailer lists | New retailer invisible to health checks |
| `check_staleness.py:49` | `EXPECTED_RETAILERS` | Never alerts if the new scraper dies |
| `query.py:221` | CLI `choices` | Can't filter by it |
| `run_daily.py:181` | per-retailer CLI flags | Can't run it alone |

**The schema `CHECK` is the sharp edge.** SQLite cannot `ALTER` a `CHECK`
constraint — changing it means the 12-step table-rebuild dance on
`retailer_listings`, which `price_snapshots` references by foreign key. Given
this project has already lost 165 snapshots once, that migration deserves its
own careful pass with a verified backup, not a drive-by.

**Mwave is the only candidate that avoids this entirely** — it is already in the
`CHECK` list. Umart, Centre Com and PLE each require the table rebuild.

The frontend needs **no work at all**: `web/src/lib/types.ts:7` already types
all six retailers and `filters.ts:8-15` already lists them, deliberately
("the display layer is prepared ahead of them so adding one is a pipeline
change, not a UI change").

## What each site actually exposes

Probed with a normal browser UA. Confidence is stated honestly — this was a
short spike, not an implementation.

### Mwave — viable, recommended

- Category pages are **server-rendered HTML**. `/graphics-cards` returned
  ~160 KB with 64 product anchors and prices in the markup.
- Parsed cleanly with BeautifulSoup on the first attempt — name, price and
  product URL all extractable. Example rows pulled live:
  `ASUS GeForce RTX 5060 Dual 8GB GDDR7 OC $779.00`,
  `Gigabyte RTX 5070 Ti WINDFORCE OC 16GB $1,999.00`,
  `Sapphire RX 9070 XT Pulse 16GB $1,279.00`.
- `?page=N` pagination works, and there is a sitemap index at
  `/sitemaps/index.xml` (12 child sitemaps) as a second enumeration route.
- `robots.txt` disallows `/searchresult*`, `/*?display*`, `/*?slug*` and
  account paths. **Category and product pages are not disallowed**; the
  sitemap is explicitly advertised. Scrape categories, not search.
- **Behind CloudFront, and it is bot-sensitive.** A request with a bare
  `Mozilla/5.0` UA got `403 Request blocked`; the same URL with a full browser
  UA plus `Accept` and `Accept-Language` returned 200. Later, after roughly
  eight rapid requests, responses came back empty — consistent with
  throttling. **The scraper must send realistic headers and rate-limit
  itself**, and should reuse the cooldown/backoff machinery already built for
  PCCG rather than inventing new.

*Not established:* how many category pages deep the GPU/CPU catalogue runs, and
whether stock status is in the grid or only on the product page. Both are
first-hour questions during implementation, not blockers.

### Centre Com — ruled out

The entire site sits behind an **AWS WAF CAPTCHA challenge**. Even
`https://www.centrecom.com.au/robots.txt` returns a `Human Verification` page
with `awsWafCookieDomainList` and a `challenge.js`/`captcha.js` pair rather than
any robots directives.

Scraping it means defeating a CAPTCHA the operator deliberately put there.
That is not a politeness problem that better headers fix, and working around it
is not something worth doing. **Drop Centre Com** unless they publish an API or
a partner feed.

### Umart — unassessed, medium confidence it is workable

- `robots.txt` is permissive for product and category paths; it disallows
  `/search.html`, `/search.php` and `/s/`. It also carries a
  `Content-Signal: ... ai-train=no` header — irrelevant to price scraping, but
  worth noting it asks not to be used as training data.
- No sitemap at `/sitemap.xml` (404).
- The category URL guessed from their old scheme
  (`/graphic-cards_1350G.html`) **redirected to the homepage**, so the URL
  scheme has changed and was not rediscovered in this spike.
- Page weight (~560 KB) and a JSON-LD block suggest a conventional storefront.

**Needs a proper 20-minute URL-discovery pass before it can be scoped.**

### PLE — unassessed, lowest confidence

- `robots.txt` is a bare `Allow: /` — the most permissive of the four.
- No sitemap at `/sitemap.xml` (404).
- `/Categories/Graphics-Cards` redirected to
  `/categories/259/graphics-cardsundefined` — a literal `undefined` in the
  path, which suggests client-side routing.
- 2.1 MB of HTML containing only **four** occurrences of the string `price`.
  That ratio points at a **client-rendered SPA**, where the grid arrives via
  XHR after load.

If that holds, PLE needs either the underlying JSON endpoint found (best case —
it becomes the *easiest* of the four, like PCCG's Algolia) or a headless
browser (worst case — a new heavyweight dependency this repo does not have).
**Worth 30 minutes with devtools open on the network tab before committing.**

## Suggested order

1. **Relax nothing, build Mwave.** No schema migration needed. Follow
   `scraper/scorptec.py` structure; reuse the PCCG cooldown/backoff module for
   CloudFront politeness. Update the nine hardcoded sites above.
2. **Then do the `CHECK`-constraint migration properly**, once, on its own —
   with a verified backup and a rehearsal against a copy. Ideally replace the
   hardcoded enum with a `retailers` lookup table so a fourth retailer is a row
   insert, not a table rebuild. This is the "hardcoded values review" already
   sitting in `STATUS.md`; a third retailer is what makes it worth doing.
3. **Then Umart or PLE**, after the 20–30 minute discovery pass each needs.
   Pick whichever turns out to expose JSON.

## Why bother

- **22 tracked products currently sit on a single retailer**, where the compare
  view has nothing to compare.
- Two retailers means a PCCG rate-limit cooldown halves the day's data. A third
  turns an outage into a degradation.
- More independent price points make the anomaly detection meaningfully more
  trustworthy.
