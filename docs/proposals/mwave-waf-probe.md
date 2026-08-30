# Mwave WAF viability probe — 31-Aug-2026

Task 0 of [`docs/superpowers/plans/2026-08-31-mwave-scraper.md`](../superpowers/plans/2026-08-31-mwave-scraper.md).
Verdict: **NO-GO at the plan's 5s cadence. Not a NO-GO on Mwave.** The cold
re-probe changed the answer: the challenge is rate-state that clears with
idleness, and the measured allowance is about **5 requests before it trips**.
The open question is no longer *whether* Mwave can be scraped but *at what
delay*. No scraper code was written.

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

## Cold re-probe -- the decisive measurement

After **~45 minutes of no contact**, a single request returned **200 / 159,056
bytes**. So the challenge is not a standing block on JS-less clients; it is rate
state, and it clears on its own.

Re-running the plan's own gate from that clean state, 8 requests at 5s:

```
page 1 -> 200 159078      page 5 -> 200 159078
page 2 -> 200 159078      page 6 -> 202 2453   <- trips here
page 3 -> 200 159078      page 7 -> 202 2453
page 4 -> 200 159078      page 8 -> 202 2453
```

**Five requests served, then challenged on the sixth**, and it stays challenged.
That is repeatable and it is the number that matters: roughly **5 requests per
~25s window** is the allowance at this spacing.

This kills the plan's stated constant -- `MWAVE_PAGE_DELAY = 5.0s` is too fast
and would fail partway through every run -- but it does *not* kill Mwave. A
once-daily scraper is under no time pressure: 20 category pages at 60s apart is
a 20-minute job that runs while nobody is watching. The next measurement is
therefore a **cadence sweep** (30s, 60s) to find the delay that sustains 20
requests, not another 5s run.

Note also that `?page=1` through `?page=5` all returned **exactly 159,078
bytes** -- the same length as the bare URL. The `page` query parameter appears
to be **ignored**, so Mwave's real pagination scheme is still undiscovered and
is a Task 4 discovery item, not a known constant.

## What would change the verdict

*(Answered above -- the cold probe returned 200, so Mwave does not belong beside
Centre Com.)*

What is still unmeasured, and is the next thing to run:

- **A cadence sweep.** From cold, 20 requests at 30s and at 60s. If either
  sustains all 20, that delay becomes `MWAVE_PAGE_DELAY` and Task 0 passes.
- **How long the trip lasts.** ~45 minutes of idleness was enough to clear it;
  the floor is unknown. It matters only for retry policy: a challenged run
  should abandon the day, not back off and retry within it.
- **The real pagination parameter**, since `?page=` is ignored.
