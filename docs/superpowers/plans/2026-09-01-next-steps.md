# Next Steps — 1-Sep-2026

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> or `superpowers:executing-plans` to work through this task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Tasks 1 and 2 are independent of each
> other; **Task 0 should happen first** because nothing from 31-Aug is live until
> it does.

**Goal:** get the 31-Aug work running in production, then close the data-quality
hole that work exposed, then decide on retailer four.

**State at the start of this plan:** `main` is clean and pushed (12 commits on
31-Aug, through `3381a4e`). Regression green: pytest **743**, vitest **397**,
e2e **68**, svelte-check 0 errors.

---

## How to kick this off

From the repo root, in a fresh session:

```
Work through docs/superpowers/plans/2026-09-01-next-steps.md, starting at Task 0.
```

Or to go straight at the main piece of work, skipping the deploy:

```
Work through Task 1 of docs/superpowers/plans/2026-09-01-next-steps.md.
```

Task 0 is the only one needing a machine that is not this one. Tasks 1–3 are
ordinary local work.

---

## Global constraints

Copied here so this plan is executable without reading the whole repo. The full
set lives in [`CLAUDE.md`](../../../CLAUDE.md).

- **Python 3.12 required.** The repo uses PEP 701 f-strings that are compile
  errors on 3.11.
- **Never delete price or product data.** Products out of scope get `tracked=0`;
  listings get `status='delisted'` / `'stale'`.
- **Never write a snapshot with a bare `open(path, "w")`** — always
  `scraper.snapshot_io.save_snapshot()`.
- **Listings are keyed by stable SKU**, never raw URL — retailers rewrite slugs.
- **Steps after ingest are best-effort** — wrap in `try/except` so they cannot
  break a run that already collected good data.
- **Entry points call `config.setup_logging()`**, never `logging.basicConfig`.
- **Log strings must be ASCII.** Use `->` not `→`; the Windows console is cp1252.
- **Full validation gate:** `python -m pytest -q` (repo root), then from `web/`:
  `npm run check`, `npm test`, `npm run test:e2e`.
- **Update `STATUS.md`** before ending a session — a dated bullet under *Recent
  changes*, never a nested "Prior update" chain.

---

## Task 0: Deploy 31-Aug to prod, and verify it

**Prod is a separate host** with its own database (confirmed 31-Aug). The DB in
this working copy is *not* live data.

- [ ] **Step 1: Pull and rebuild on the prod host**

```bash
cd /path/to/Trackaroo
git pull
docker stop trackaroo && docker rm trackaroo
docker build -t trackaroo .
# re-run the docker run command from DEPLOYMENT.md:127
docker logs -f trackaroo
```

The MSYS mount trap documented in STATUS is Windows-Git-Bash-only; a Linux host
is unaffected.

- [ ] **Step 2: Confirm the startup did its work**

The entrypoint runs `seed.py` and `migrate.py` itself, so nothing needs running
by hand. In the logs expect:

- `Inserted: 1` from seed — the `Core i9-14900` added 31-Aug.
- `[MIGRATE] retailer_listings rebuilt; CHECK now permits: scorptec, pccg, mwave, umart, centrecom, ple`
  — this is the table rebuild. It is idempotent; a second boot logs `[SKIP]`.

- [ ] **Step 3: Expect umart warnings on the first run, and only the first**

`umart` is now in `config.ACTIVE_RETAILERS`, so the health checks and the
staleness monitor expect data from it **before the first umart scrape has run**.
Until that first daily run completes, expect:

- `check_json_files` warning about missing `cpu_umart_*.json` / `gpu_umart_*.json`
- `check_today_coverage` reporting no umart data
- `check_staleness.py` flagging umart as absent

**This is correct behaviour, not a fault.** If it persists *after* a successful
daily run, that is a real problem — look at the umart scraper log first.

- [ ] **Step 4: Verify the dashboard**

- The category headers should read **"N of M tracked"**, not a bare count.
- `/products?retailer=umart` should list Umart listings.
- The anomaly section should be quiet unless a price genuinely moved that day.

---

## Task 1: Age out listings nobody has seen — the main piece of work

**The problem, measured on 31-Aug:** `check_delisted.py:141` hardcodes
`WHERE l.retailer = 'scorptec'`, so **nothing ever ages out a PCCG or Umart
listing**. 13 active listings (8 pccg, 5 scorptec) had not been seen for 7+ days
and would stay `active` forever.

**Why it matters now.** The dashboard's "N of M tracked" headline, added 31-Aug,
counts `status='active'`. Every listing that quietly disappears keeps inflating
that number — the exact dishonesty that headline was built to fix. Umart will
drift fastest of the three: its category grid lists **only purchasable items**
(217 GPUs, all in stock), so its listings churn in and out constantly.

**Files:**
- Create: `check_stale_listings.py`
- Create: `unit_testing/test_check_stale_listings.py`
- Modify: `config.py` (a knob beside `STALE_THRESHOLD_DAYS`, ~line 140)
- Modify: `run_daily.py` (wire it in beside the delisted check, ~line 318)

### The one subtlety that makes this dangerous

**Do not compare against `now`.** Compare a listing against **its own retailer's
most recent snapshot date**.

If a retailer's scraper dies for eight days and the rule is "no snapshot in 7
days → stale", the next run marks *that retailer's entire catalogue* stale in one
pass — a mass mistagging that looks exactly like the retailer going out of
business. PCCG makes this concrete rather than hypothetical: its circuit breaker
writes `data/pccg_cooldown.json` and later runs **skip PCCG entirely** for
`PCCG_COOLDOWN_HOURS`, so multi-day silence from a healthy retailer is a normal
operating state.

The rule that survives that: a listing goes stale when **its retailer was
scraped recently and this listing was not in it.**

- [ ] **Step 1: Write the failing tests**

Cover, at minimum:

1. A listing whose retailer has fresh data, but which has no snapshot for N days → `stale`.
2. A listing whose **retailer has no recent data at all** → left `active`. *(The mass-mistagging guard. This is the test that matters most; write it first.)*
3. A listing already `delisted` → untouched (do not downgrade a confirmed delisting to a guess).
4. A listing seen today → untouched.
5. A retailer with no listings at all → no crash, no results.
6. Idempotent: a second run changes nothing.
7. It never deletes rows — count before == count after.

- [ ] **Step 2: Run the tests and watch them fail** — `python -m pytest unit_testing/test_check_stale_listings.py -v`

- [ ] **Step 3: Add the config knob**

In `config.py`, beside `STALE_THRESHOLD_DAYS` (~line 140):

```python
# Days a listing may go unseen -- while its own retailer IS being scraped --
# before it is marked stale. Compared against the retailer's latest snapshot,
# never against now: a retailer in cooldown is silent but healthy, and
# comparing against now would mark its whole catalogue stale in one pass.
STALE_LISTING_DAYS = _env_int("TRACKAROO_STALE_LISTING_DAYS", 7)
```

Document it in the module docstring's env table and in `.env.example`.

- [ ] **Step 4: Implement `check_stale_listings.py`**

Follow the shape of `check_staleness.py`: reads and writes only the DB, no
network, never raises, `run()` entry point returning a summary, and a `--dry-run`
flag. Log one line per listing marked, plus a summary count.

- [ ] **Step 5: Wire it into `run_daily.py`**

Beside the delisted check (~line 318), inside a `try/except` — it is a
post-ingest step and must never break a run that already collected good data.

- [ ] **Step 6: Verify against the real DB**

```bash
python check_stale_listings.py --dry-run
```

Expect roughly the 13 listings identified on 31-Aug (8 pccg, 5 scorptec), and
**zero** umart on day one. Sanity-check a couple by hand before running it for
real; take a backup first (`python backup_db.py`).

- [ ] **Step 7: Full validation gate, then commit**

### Note on Scorptec

`check_delisted.py` stays as it is. It marks `delisted` only on a **positive**
404/410, which is stronger evidence than absence, and leaves unknown pages
alone. The new check is the weaker, retailer-agnostic net beneath it: `delisted`
means "confirmed gone", `stale` means "stopped appearing". Do not merge them.

---

## Task 2: Mwave as retailer four — decide first, then build

**Do not start this until Task 1 is done and deployed.** It is optional; Task 1
is not.

The schema already accepts `mwave` (the 31-Aug `CHECK` migration), so **no
migration is needed** — this is now just a scraper plus one line in
`config.ACTIVE_RETAILERS`.

**Read first:** [`docs/proposals/mwave-waf-probe.md`](../../proposals/mwave-waf-probe.md)
and the 31-Aug section of [`THIRD_RETAILER.md`](../../proposals/THIRD_RETAILER.md).
[`2026-08-31-mwave-scraper.md`](2026-08-31-mwave-scraper.md) is **superseded in
part** — its Tasks 2–4 target the wrong URL and its Task 3 premise is disproved.

**What is actually true about Mwave:**

- `/graphics-cards` is a curated landing page: 31 cards, no pagination, `?page=`
  and `?cnt=` both ignored.
- The real endpoint is
  `/searchresult?w=graphics+card&cnt=100&srt=<offset>&isort=score&view=grid&af=categoryPath%3AGraphics+Card`
  — server-rendered, **100 products per request**, 278 total, paged by `srt=`
  offset.
- Cards carry name, `.SalesPrice`, stock, URL and a stable SKU (`AC84825`, also
  the URL suffix).
- **The WAF limit is a count, not a rate**: five requests then challenged, at 5s
  *and* at 30s spacing. ~45 minutes of idleness clears it.

**So a run is ~5 requests and sits exactly on the allowance, with no headroom for
a retry.** A challenged fetch must **abandon the day**, not retry inside the run.
That fragility is the whole decision: this scraper will fail intermittently in a
way Scorptec/PCCG/Umart do not.

- [ ] **Step 1: Make the call, and record it** in `THIRD_RETAILER.md`. Either
  accept intermittent gaps, or spread a run across ~4 cold periods (~3 hours),
  which is a different scraper from anything the repo has.
- [ ] **Step 2:** only then, rewrite Tasks 2–4 of the Mwave plan against
  `/searchresult` and build it, following `scraper/umart.py` as the closest model.

---

## Task 3: Confirm the weekly spec sync fires on prod — 10 minutes

- [ ] Locally the last spec sync was **13 days old against a 14-day threshold**,
  because the container has not been running on this machine. On prod it should
  run Sunday 03:00 (`SPEC_SYNC_DOW` / `SPEC_SYNC_HOUR`). Confirm from the
  container log rather than assuming — `check_spec_coverage` reports freshness,
  so a stale figure after a Sunday means the in-container schedule is not firing.

*(The `STATUS.md` housekeeping originally listed here was done on 31-Aug: items
1 and 7 of "What's NOT done yet" are current, and item 8 now tracks Task 1.)*

## Deliberately out of scope

- **`check_delisted.py` for Umart.** Umart's grid lists only purchasable items,
  so a vanished listing means out of stock, **not** delisted. Task 1's stale rule
  is the right tool; a positive-404 check would mislabel ordinary stock churn.
- **The anomaly detector's option (d)** (median + MAD). The 31-Aug work made the
  check an event detector, which was the real problem. Revisit only if it proves
  noisy in practice.
- **RAM tracking** ([`RAM_SCOPE.md`](../../proposals/RAM_SCOPE.md)) — planned,
  not started, not required.
- **Reverse proxy / TLS** — deferred while the dashboard stays on the LAN.
- **The 2026-08-29 data gap** — no snapshots exist for that day and none can be
  recovered. Leave it.
