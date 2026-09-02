# Adding a Third Retailer — Feasibility & Scope

**Status:** Scorptec, PCCG and Umart are live (Umart shipped 31-Aug-2026).
**Mwave, the retailer-four candidate this document originally led to, was
decided against 3-Sep-2026** — see the bottom of this file and the decision
log (`docs/ARCHITECTURE.md` Part 3, "Retailer four: Mwave decided against,
not attempted"). Kept for the historical WAF research, which is still
accurate.

Candidates considered: **Mwave, Umart, Centre Com, PLE.**

## Recommendation

**Build Mwave first, and only Mwave — but gate it on a viability probe.** It is
the largest of the four, the only one already permitted by the database schema,
and its pages parse as a conventional server-rendered scrape of the same shape
as Scorptec. It is also behind AWS WAF and *will* challenge a scraper that
bursts, so the first task is measuring whether a realistic daily cadence trips
it. Add a second retailer only once Mwave has run clean for a fortnight.

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

### Mwave — recommended, gated on a WAF viability probe

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
- **Behind AWS WAF — the same protection Centre Com was ruled out for.**
  This was found late in the spike and corrects an earlier reading of it as
  plain CloudFront rate-limiting. The behaviour is graduated:
  - A bare `Mozilla/5.0` UA got `403 Request blocked`.
  - A full browser UA plus `Accept` / `Accept-Language` returned 200 with real
    content, repeatedly.
  - After roughly a dozen requests in a few minutes, the same URL began
    returning **HTTP 202 with an AWS WAF challenge page** —
    `window.awsWafCookieDomainList = ['www.mwave.com.au','mwave.com.au']`
    plus `challenge.js`, byte-for-byte the same mechanism as Centre Com.

  **The difference from Centre Com is threshold, not vendor.** Centre Com
  challenges immediately, on `robots.txt` itself. Mwave serves real pages and
  only challenges once a burst trips it.

  That difference is probably decisive in Mwave's favour — a daily scraper
  making ~20 requests once every 24 hours looks nothing like the burst that
  tripped it here — **but that is an assumption, not a measured fact.** It is
  the single thing to establish before any scraper code is written. If a
  polite daily cadence still gets challenged, Mwave goes the way of Centre Com
  and the recommendation moves to Umart.

  If it proceeds: realistic headers are mandatory, requests must be spaced,
  and it should reuse the cooldown/breaker machinery already built for PCCG —
  a challenge response must trip a cooldown, never a retry storm.

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

## 31-Aug-2026: both candidates re-probed, and both assessments were wrong

The 30-Aug spike got Mwave and Umart backwards in opposite directions. Neither
conclusion survives contact with the actual sites.

### Mwave is viable -- but not the way the plan describes

The plan assumed category pages plus a polite page delay. Both are wrong:

- `/graphics-cards` is a **curated landing page**: exactly 31 cards, and **no
  pagination links at all**. `?page=N` is ignored (pages 1-5 returned byte-identical
  responses), and so is `?cnt=500`.
- The real listing endpoint is **`/searchresult`**, which takes a page size and an
  offset and is fully server-rendered:

  ```
  /searchresult?w=graphics+card&cnt=100&srt=<offset>&isort=score&view=grid
                &af=categoryPath%3AGraphics+Card
  ```

  One request returns **100 products** (`cnt` caps at 100 -- asking for 200 still
  yields 100), and the page states the total: **278 Products** in Graphics Card.
  Paging is by `srt=` offset, not a page number.
- Each card carries everything the schema needs: name, `.SalesPrice`, stock, the
  product URL, and a **stable SKU** (`AC84825`, also the URL suffix) -- so listings
  can be keyed by SKU rather than by slug, as the constraints require.

**So a daily run is ~3 requests for GPUs and ~2 for CPUs, not 20.** That lands
right on the measured WAF allowance of ~5 requests per cold period, which is the
catch: there is no headroom for a retry, and a single failed fetch cannot simply
be re-attempted inside the run. A run should fetch, and on a challenge abandon
the day rather than retry -- the cooldown pattern PCCG already uses.

### Umart is server-rendered, and the URL scheme is now known

The spike recorded Umart as "unassessed" after a guessed URL redirected to the
homepage. That guess used the **wrong scheme entirely**: `_1350G.html` is the
*goods* form. The real category URLs are path-based with a trailing numeric id,
and they are listed on the homepage -- no guessing needed:

| Category | URL | Pages |
|---|---|---|
| GPUs | `/pc-parts/computer-parts/graphics-cards-gpu-610` | 11 |
| CPUs | `/pc-parts/computer-parts/cpu-processors-611` | 3 |

20 products per page, `?page=N`, so **~14 requests a day** for both categories.
`pagesize` is not a usable query parameter (the control is a `<span>` of UI
state; `?pagesize=100` is ignored).

The "client-rendered SPA" worry does **not** apply to Umart -- that was PLE. Each
`.goods-item` card is in the HTML with name, brand, `.goods-price`, stock text,
and a product URL whose numeric suffix is the SKU:

```
Asus Dual GeForce RTX 5060 8G OC   $ 579.00   In Stock   sku 95655
Asus Dual Radeon RX 9060 XT 16G    $ 749.00   In Stock   sku 90401
```

*(A caution for whoever implements it: the price renders as `$&nbsp;579.00`, so a
naive `\$[\d,]+` regex over the raw HTML finds **nothing** and the page looks
client-rendered. It is not -- parse it with BeautifulSoup, which decodes the
entity. This cost time twice, once in the 30-Aug spike and once on 31-Aug.)*

Umart has **no WAF challenge**, and `robots.txt` permits product and category
paths. So 14 plain requests a day carry none of Mwave's fragility.

### Which to build first

|  | Mwave | Umart |
|---|---|---|
| Requests/day | ~5 | ~14 |
| WAF | AWS WAF, ~5-request budget -- **no retry headroom** | none |
| Schema `CHECK` | already listed -- **no migration** | **needs the table rebuild** |
| Parsing | server-rendered, SKU present | server-rendered, SKU present |
| Restores lost coverage | unknown | **yes** -- stocks RTX 3060, GT 710/730 and other parts that Scorptec and PCCG have sold out of |

The trade is now explicit: **Mwave is cheaper to integrate but operationally
fragile; Umart is operationally safe but costs the `CHECK`-constraint migration
up front.** Umart is also the one that answers the coverage problem found the
same day -- 42 of 100 tracked products have no listing at Scorptec or PCCG
because those two have sold out of the previous generation, and Umart still
stocks a chunk of it.

## Suggested order

0. **Measure the WAF first.** Before any code: confirm a polite, daily-cadence
   request pattern is served real HTML rather than an AWS WAF challenge. This
   is a go/no-go gate, not a formality.
1. **Then build Mwave.** No schema migration needed. Follow
   `scraper/scorptec.py` structure; reuse the PCCG cooldown/breaker module so a
   WAF challenge trips a cooldown instead of a retry storm. Update the nine
   hardcoded sites above.
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

## 3-Sep-2026: Mwave (retailer four) decided against

By this date Scorptec, PCCG and Umart were all live (Umart shipped 31-Aug),
and Umart had already delivered the coverage case above — 5 previously
unlisted products restored, GPUs 23→25/46, CPUs 34→37/54. That left one open
question for Mwave specifically, never measured until now: **does it restore
coverage the way Umart did?**

Checked all 39 tracked-but-unlisted products (22 GPU, 17 CPU) against
Mwave's complete catalogue — all 3 GPU pages (276 of 278 products via
`/searchresult?w=graphics+card&cnt=100&srt=<offset>`) and a CPU search
(`w=processor`, 100 products; `w=cpu` itself returns zero results — the site
doesn't index that term). That's exactly 5 requests, which also reconfirmed
the WAF budget measured below: all 5 served, none challenged, right at the
edge.

**Result: 0 of 22 unlisted GPUs, 2 of 17 unlisted CPUs (`i5-14600KF`,
`i9-14900F`).** A third apparent CPU hit (`Ryzen 9 7950X`) is refurbished
stock only; three more were false positives from a loose substring
matcher — Mwave stocks the KF/X3D/X variant, not the base part tracked.
Mwave's catalogue is dominated by current-gen stock (RTX 50-series,
RX 9000-series) exactly like the three retailers already live; the
RX 6000/7000-series and RTX 30/40-series cards driving the gap are equally
end-of-life there.

**Decision: park it.** 2 real new listings out of 39 gaps doesn't justify a
scraper with zero retry margin against a count-based WAF allowance (§ above:
5 requests served, challenged on the 6th, regardless of spacing). No scraper
code was written. Revisit only if a specific future watchlist addition is
confirmed to live at Mwave and nowhere else — see the full writeup in
`docs/ARCHITECTURE.md` Part 3.
