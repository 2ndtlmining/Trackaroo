# Mwave WAF viability probe — 31-Aug-2026

Task 0 of [`docs/superpowers/plans/2026-08-31-mwave-scraper.md`](../superpowers/plans/2026-08-31-mwave-scraper.md).
Verdict: **NO-GO on this measurement, pending one cold re-probe.** No scraper
code was written.

## Step 1 — has yesterday's block aged out?

Single `GET https://www.mwave.com.au/graphics-cards`, full browser headers, no
cookies. Two consecutive attempts, seconds apart:

| # | Status | Size | Reading |
|---|---|---|---|
| 1 | 202 | 2,029 | WAF challenge |
| 2 | **200** | **159,056** | real page — 129 `price` occurrences |

So the block had **not** aged out overnight, but the site did serve one clean
page. That single 200 is the only real HTML obtained all session, and it is the
reason this is written up as "re-probe" rather than a flat NO-GO.

## Step 2 — one realistic daily run (8 requests, 5s apart)

`?page=1..8`, same headers, no cookies:

```
page 1 -> 202 2029    page 5 -> 202 2453
page 2 -> 202 2029    page 6 -> 202 2453
page 3 -> 202 2029    page 7 -> 202 2453
page 4 -> 202 2453    page 8 -> 202 2453
```

**0 of 8 served.** The plan's bar was all eight at 200.

## Step 3 — what is actually triggering it

Ruled out the two obvious confounders after a 30s pause, 10s between requests:

| Probe | Status |
|---|---|
| A bare URL, no cookie | 202 |
| B `?page=2`, no cookie | 202 |
| C bare URL, cookie jar seeded | 202 |
| D `?page=2`, reusing jar | 202 |
| E `?page=3`, reusing jar | 202 |

The query string is **not** the trigger, and a cookie jar does not help — the
challenge page sets no cookie curl can carry, because the token is issued by
JavaScript. 14 of 15 requests this session were challenged, across a 5s cadence,
a 10s cadence and a 30s pause.

## Correction to the detection heuristic

The healthy 200 page **contains** `challenge.js` and the string `awswaf` — the
AWS WAF JS SDK is embedded in Mwave's normal `<head>`:

```html
<script src="https://3df8e74669ee.edge.sdk.awswaf.com/.../challenge.js" defer></script>
```

It does **not** contain `awsWafCookieDomainList` (0 occurrences) or `gokuProps`
(0). So `is_waf_challenge` as specified in Task 3 is correct and will not
false-positive — but `challenge.js` / `awswaf` must never be added as markers.
The cheapest true signal is **HTTP 202 with a ~2 KB body**; a served page is
~159 KB.

## Also confirmed

`https://www.mwave.com.au/robots.txt` returns **200** with real directives —
unlike Centre Com, whose robots.txt is itself a CAPTCHA. Mwave is not hostile by
policy, only by rate rule.

## What would change the verdict

One **cold** single request after several hours of no contact from this IP. If
that returns 200 and a second 60s later also returns 200, the challenge is
rate-state that a once-daily scraper would never enter, and Task 0 can be re-run
properly. If it returns 202 cold, Mwave challenges every JS-less client by
default and belongs beside Centre Com.
