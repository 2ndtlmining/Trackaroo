# IMPROVEMENT.md — Real Spec Data (CPU + GPU)

**Status:** Proposed, not yet built
**Priority:** Additive only. Price tracking remains the site's primary function and nothing in this doc may slow down, block, or risk the daily price pipeline.
**Audience:** This doc is written so a local model with no other context can implement it directly against the existing Trackaroo repo. It assumes familiarity with README.md, SPEC.md, SCOPE_RULES.md, and DECISIONS.md — read those first if not already loaded.

---

## 1. Goal

Replace the hand-maintained parts of product classification with real hardware spec data, and surface that data on the product page — **below** the price graph, never above or instead of it. Two data domains: GPUs and CPUs, sourced from external JSON datasets refreshed weekly, not scraped live per-request.

## 2. Priority order (do not violate)

1. Price tracking (existing `run_daily.py` pipeline, `price_snapshots` table) — untouched, unaffected, highest priority.
2. Site performance on the main price list/chart pages — must not regress. Spec data is not joined into list queries.
3. Spec sync — a separate, weekly, best-effort job. If it fails, the site keeps working with stale or absent spec data. It must never be able to break ingestion, delete price data, or take down `run_daily.py`.
4. Product page spec display — additive UI below the price graph.

If any implementation choice below creates a conflict with priorities 1–2, stop and flag it rather than proceeding.

**Note:** §10 (PCCG reliability fixes) is a bug fix to the existing price pipeline, not new spec-data functionality. It should be implemented first, independently of §3–§9, since it addresses a real production issue (the recurring PCCG 429 situation) rather than adding a new capability.

## 3. Data sources

### 3.1 GPU (decided)

- **Source:** [RightNow-AI/RightNow-GPU-Database](https://github.com/RightNowAI/gpu-database) — plain JSON files on GitHub, sourced from TechPowerUp via the `dbgpu` project.
- **Fetch URL pattern (raw JSON, no auth):**
  - `https://raw.githubusercontent.com/RightNowAI/gpu-database/main/data/nvidia/all.json`
  - `https://raw.githubusercontent.com/RightNowAI/gpu-database/main/data/amd/all.json`
  - Confirm exact per-vendor file paths against the repo's `data/` directory at implementation time — list the directory via the GitHub API or a `git clone --depth 1` rather than guessing additional filenames.
- **License:** MIT. Attribution to TechPowerUp appreciated but not contractually required by this dataset's own license — still worth a line in README.md's data sources section.
- **Why this over TechPowerUp directly:** no scraping, no bot-detection risk, no ToS gray zone (same politeness principle already applied to dropping Mwave), already-normalized JSON, sits on a domain already in the project's allowed egress list (`raw.githubusercontent.com`, `github.com`).

### 3.2 CPU (needs one implementation-time decision — see §3.3)

No single GitHub JSON source covers both Intel and AMD with the same shape RightNow-AI provides for GPUs. Two candidates:

- **Option A — felixsteinke/cpu-spec-dataset:** covers both Intel and AMD, sourced directly from AMD.com and Intel ARK (not TechPowerUp). Ships as CSV plus a Dockerized Spring Boot API. Better provenance (vendor-direct), but requires either running their API container or consuming the CSVs directly from the repo.
- **Option B — divinity76/intel-cpu-database (Intel only) + a second AMD-only source:** matches the GitHub-raw-JSON pattern used for GPUs, but only solves half the problem on its own and needs a second, separately-vetted AMD source found and validated before this is usable.

**Recommendation: Option A (felixsteinke/cpu-spec-dataset).** One source, both vendors, vendor-direct provenance. Consume the CSVs directly from the repo's raw GitHub URLs (same low-risk fetch pattern as the GPU source) — do not stand up their Docker API just for this; that's unnecessary infrastructure for a weekly batch read.

### 3.3 Decision needed before coding starts

Confirm the exact CSV file paths and column schema in `felixsteinke/cpu-spec-dataset` (clone or browse the repo, list `datasets/` or equivalent). If the CSV structure turns out to be unworkable (e.g. requires the API layer to normalize), fall back to Option B and flag that a second AMD JSON source needs sourcing and vetting before proceeding. Do not silently substitute a scraped TechPowerUp CPU source as a shortcut — that reopens the exact scraping/ToS risk this whole approach exists to avoid.

## 4. Data model changes

### 4.1 New table: `specs`

One row per canonical product line (not per retailer listing, not per daily snapshot). Lives alongside `products`, joined by `product_id`.

```sql
CREATE TABLE specs (
    spec_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id        INTEGER NOT NULL REFERENCES products(product_id),
    source             TEXT NOT NULL,        -- 'rightnow-gpu-db' | 'cpu-spec-dataset'
    source_record_key  TEXT NOT NULL,        -- the identifying field/name from the source dataset, kept for traceability and re-matching
    category            TEXT NOT NULL,        -- 'gpu' | 'cpu' (matches products.category)
    architecture         TEXT,                 -- e.g. 'Blackwell', 'RDNA 4', 'Zen 5', 'Arrow Lake'
    generation            TEXT,                 -- e.g. 'RTX 50', 'Ryzen 9000'
    launch_date            TEXT,                 -- ISO date, nullable if unknown
    launch_msrp_usd         REAL,                 -- as published in source dataset; do not convert currency here, do it at display time
    -- GPU-specific (nullable for CPU rows)
    vram_gb                  REAL,
    memory_bus_width_bit      INTEGER,
    memory_type                TEXT,             -- e.g. 'GDDR7'
    tdp_watts                    INTEGER,
    core_count                    INTEGER,        -- shading units for GPU, physical cores for CPU — see note below
    -- CPU-specific (nullable for GPU rows)
    thread_count                   INTEGER,
    base_clock_mhz                   INTEGER,
    boost_clock_mhz                    INTEGER,
    socket                                TEXT,
    cache_l3_mb                            REAL,
    raw_json                                 TEXT NOT NULL,   -- full original source record, verbatim, for future fields without a migration
    last_synced_at                            TEXT NOT NULL,   -- ISO timestamp, set by sync job
    UNIQUE(product_id, source)
);
```

Notes:
- `core_count` is intentionally shared between GPU shading-unit count and CPU physical-core count rather than having two columns — document this clearly in SPEC.md if adopted, or split into `gpu_core_count` / `cpu_core_count` if that reads as too overloaded. Local model's call; either is fine, but pick one and be consistent with naming elsewhere in schema.sql.
- `raw_json` exists so that when you want a new field later (e.g. RT core count, PCIe gen) you don't need a schema migration to get at it — it's already in the row. Extract it into a proper column only once you're using it in a query, not speculatively.
- No foreign key to `retailer_listings` or `price_snapshots`. Specs describe the canonical product, not a retailer's page for it.

### 4.2 Matching: `products` → external spec dataset

This is the hardest part and needs to be treated as seriously as the existing retailer product-matching logic in `test_matching.py`.

1. **Do not match on exact string equality of names.** Retailer names ("ASUS ROG Astral RTX 5090 32GB") vs spec dataset names ("GeForce RTX 5090") will not line up directly.
2. **Match at the `products` (canonical) level, not the `retailer_listings` level.** `products` already represents the canonical model (brand + model + category + generation tier per the existing data model) — that's the right granularity to attach one `specs` row to.
3. **Matching strategy, in order of preference:**
   - Normalize both sides: strip brand/AIB-partner prefixes, strip marketing suffixes ("OC", "Founders Edition" handling — decide per-dataset whether FE/reference specs are the ones you want, since AIB variants mostly share the reference GPU's core specs anyway), lowercase, collapse whitespace.
   - Exact match on normalized model string first.
   - Fuzzy match (e.g. `thefuzz`/`rapidfuzz`, consistent with the `dbgpu[fuzz]` dependency already referenced in the GPU source's own tooling) as a fallback, with a similarity threshold (start at 90, tune based on false-positive rate observed in testing).
   - **Anything below the threshold does not get auto-matched.** Log it to an unmatched report instead (see §6.3). Do not guess.
4. **No silent overwrites.** If a `product_id` already has a `specs` row from a previous sync and the new sync's match is different, do not overwrite automatically — flag for review. Spec data should be as stable and trustworthy as the "never delete price data" rule is for prices.

## 5. Sync job design

### 5.1 New script: `sync_specs.py`

Mirrors the shape of `run_daily.py` conceptually (one command, dry-run support, logging) but is a wholly separate entry point — never called from or by `run_daily.py`.

```
python sync_specs.py                 # full sync: fetch + match + write, both categories
python sync_specs.py --category gpu  # GPU only
python sync_specs.py --category cpu  # CPU only
python sync_specs.py --dry-run       # fetch + match + report, no DB writes
python sync_specs.py --report-only   # print last sync's unmatched/conflict report, no fetch
```

### 5.2 Cadence

Weekly, not daily. Specs do not change once a part has launched (occasional corrections aside). Run via the same cron/systemd-timer mechanism already used for `run_daily.py`, as a separate scheduled entry — e.g. Sunday 03:00, well clear of the daily price run's schedule.

### 5.3 Pipeline steps

1. Fetch source JSON/CSV (GPU: RightNow-AI raw files; CPU: felixsteinke dataset per §3.2/3.3) over HTTPS. Timeout and retry with backoff (reuse whatever HTTP client conventions `ingest.py`/`fetch_test.py` already use).
2. Parse into an in-memory list of normalized records (one dict per product, mapped to the `specs` column set in §4.1).
3. Load current `products` table (both categories, `tracked=1` and `tracked=0` — spec data for untracked/historical products is still valid to have).
4. Run the matching strategy from §4.2 for every `products` row against the fetched dataset.
5. For matches above threshold with no existing `specs` row: insert.
6. For matches above threshold where an existing `specs` row differs meaningfully (compare `raw_json` or key fields): do not overwrite, add to conflict report.
7. For `products` rows with no confident match: add to unmatched report, leave `specs` absent for that product (product page simply shows no spec panel for it — see §7.4).
8. Write `last_synced_at` on every row touched this run.
9. Emit a summary (counts: matched/new, matched/unchanged, conflicts, unmatched) — same style as `health_checks.py`'s existing summary output.

### 5.4 Failure handling

- Source unreachable / malformed response → log, exit non-zero, **do not touch the `specs` table at all**. Last-known-good spec data stays in place untouched.
- Partial failure (e.g. GPU source fetched fine, CPU source failed) → each category is independent; a CPU fetch failure must not abort the GPU sync that already succeeded, and vice versa.
- No row in `specs` is ever deleted by this job. If a product's spec source record disappears from upstream, leave the existing row in place (same "never delete" principle as price data) and just don't update `last_synced_at` for it.

## 6. Testing requirements

Add to `unit_testing/`, following the existing per-module pattern:

- `test_specs_schema.py` — schema/table creation, constraints.
- `test_specs_matching.py` — normalization and fuzzy-match logic against a fixed set of known tricky cases (AIB-partner names, FE vs partner-card naming, CPU with/without suffix like "X3D", "KF"). Include cases that should deliberately NOT match, to guard against false positives.
- `test_sync_specs.py` — pipeline integration test using an in-memory DB and mocked HTTP responses (do not hit the real GitHub URLs in tests), covering: fresh sync, no-op re-sync, conflict detection, partial-category failure isolation.

Target: keep the whole suite fast, consistent with the existing ~0.8s for 188 tests — mock all network calls.

## 7. Product page changes

### 7.1 Layout (this is the actual UI requirement driving this whole doc)

Top to bottom, in this order:

1. Product title / identity (as today).
2. **Price graph — unchanged position, unchanged priority.** This is still the first thing a visitor sees.
3. Price stats (current low, trend, retailer comparison — whatever already exists here).
4. **New: Spec panel.** Sits below the price content, not above it, not replacing anything.

### 7.2 Spec panel content

Keep it short — this is a supplementary panel, not a full spec sheet. Show only the fields that actually help someone decide, in this priority order:

**GPU:**
- Generation / architecture (e.g. "RTX 50 series — Blackwell")
- VRAM (size + type, e.g. "32GB GDDR7")
- Launch MSRP (with "current price vs MSRP" delta if you have it — this was flagged earlier as the single most useful derived number)
- Core count
- TDP

**CPU:**
- Generation / architecture (e.g. "Ryzen 9000 — Zen 5")
- Cores / threads
- Launch MSRP (+ delta vs current price, same as GPU)
- Base / boost clock
- TDP

A "show full specs" expand/collapse can hold the rest (bus width, cache, socket, etc.) if you want it, but it must be collapsed by default — the panel's default state should not add meaningful page weight or visual competition with the price graph.

### 7.3 Data fetching for this panel

Specs are static-ish (weekly refresh) — fetch them with the product page's existing detail query, not as a separate client-side round trip, and not joined into any list/index page query. One extra `SELECT ... FROM specs WHERE product_id = ?` on the product detail page load is fine; joining `specs` into the main price list/chart pages is not.

### 7.4 No spec data available

Some tracked products won't have a confident match (§4.2 step 7). In that case the spec panel simply doesn't render for that product — no placeholder, no "specs coming soon," no broken-looking empty state. The page works exactly as it does today for that product.

## 8. What this explicitly does NOT change

- `run_daily.py`, the scraper modules, `ingest.py`, `health_checks.py` — no modifications.
- `price_snapshots` / `retailer_listings` schema — no modifications.
- `watchlist.csv` / `SCOPE_RULES.md` generation-window rule — out of scope for this doc. (A follow-up idea, discussed separately, is using the spec dataset to auto-suggest watchlist changes when a new generation launches — deliberately not included here; this doc is scoped to spec display only, not scope automation, to keep this change reviewable and low-risk.)
- Main price list / index page — no new joins, no new columns rendered there.

## 9. Rollout order

1. Confirm CPU source (§3.3) and finalize the exact `specs` schema (§4.1) — small adjustments expected once real source data is in hand.
2. Build `sync_specs.py` for GPU only first (source already decided), get matching working and validated against the real watchlist, with tests.
3. Add CPU to `sync_specs.py` once the source is confirmed.
4. Ship the product-page spec panel (§7) once spec data exists in the DB for a meaningful share of tracked products.
5. Update README.md's documentation-reading-order / data-sources section and DECISIONS.md with the rationale captured in this doc (GitHub-JSON-over-scraping, decoupled weekly sync, no-overwrite matching).

## 10. PCCG reliability — fixing the recurring 429 hard-rate-limit issue

**This section is independent of the spec-data work above and should be done first.** It's a bug fix to something already in production, not a new feature, and it's low-risk/high-value: it directly addresses the recurring "Open item: PCCG is still hard-rate-limiting on every request today" situation.

### 11.1 Root cause: a real infinite-loop bug in the retry logic, not just aggressive rate limiting

Reviewed `scraper/pccg.py` directly. Both `algolia_single_search()` (lines ~171–241) and `algolia_batch_search()` (lines ~243–333) share this shape:

```python
while page < max_pages:
    ...
    for attempt in range(ALGOLIA_MAX_RETRIES):
        try:
            r = requests.post(...)
            if r.status_code == 429:
                wait = ALGOLIA_RATE_LIMIT_WAIT_SECONDS * (attempt + 1)
                LOGGER.warning(...)
                time.sleep(wait)
                continue
            ...
            page += 1
            time.sleep(0.3)
            break
        except requests.RequestException as e:
            LOGGER.error(...)
            return all_results
    # <- nothing here
return all_results
```

If **every** attempt in the `for attempt in range(ALGOLIA_MAX_RETRIES)` loop hits a 429, the `continue` statement just moves to the next retry attempt. Once the range is exhausted, the `for` loop ends normally — there is no `break`, but also nothing that stops or returns from the *outer* `while` loop. Control falls back to the top of `while page < max_pages`, `page` was never incremented, and the exact same request is built and retried again — forever. There is no path out of this state short of the process being killed or timing out at a level above the scraper (e.g. `SCRAPER_TIMEOUT_SECONDS` in `run_daily.py`'s `subprocess.run(..., timeout=...)`, if that's even generous enough to eventually fire).

This matches the symptom exactly: "PCCG is still hard-rate-limiting on every request today" isn't a case of the existing backoff being too weak — it's the scraper getting stuck in a loop that never gives up and never reports failure cleanly, which is why it's showing up as a manual "should I retry or leave it?" judgment call instead of something the system reports and recovers from on its own.

**Fix:** track whether the retry loop was exhausted, and if so, stop — don't let the outer `while` repeat the same page again.

```python
while page < max_pages:
    ...
    retries_exhausted = True
    for attempt in range(ALGOLIA_MAX_RETRIES):
        try:
            r = requests.post(ALGOLIA_URL, json=payload, headers=HEADERS, timeout=ALGOLIA_TIMEOUT_SECONDS)
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else ALGOLIA_RATE_LIMIT_WAIT_SECONDS * (attempt + 1)
                LOGGER.warning("Rate limited (attempt %d/%d), waiting %ds...", attempt + 1, ALGOLIA_MAX_RETRIES, wait)
                time.sleep(wait)
                continue
            if r.status_code != 200:
                LOGGER.error("Algolia API error: %s - %s", r.status_code, r.text[:200])
                return all_results
            try:
                data = r.json()
            except ValueError:
                LOGGER.error("Algolia returned non-JSON response (likely a WAF/challenge page), body[:200]: %s", r.text[:200])
                return all_results
            if "results" not in data:
                LOGGER.error("Algolia API unexpected response")
                return all_results
            # ... existing processing ...
            retries_exhausted = False
            page += 1
            time.sleep(0.3)
            break
        except requests.RequestException as e:
            LOGGER.error("Algolia batch request error: %s", e)
            return all_results
    if retries_exhausted:
        LOGGER.error(
            "Giving up after %d retries on page %d — PCCG appears to be rate-limiting all requests right now.",
            ALGOLIA_MAX_RETRIES, page,
        )
        return all_results
return all_results
```

Apply the same `retries_exhausted` pattern to `algolia_single_search`. Also note the `Retry-After` header handling above — Algolia/Cloudflare-fronted 429s often carry it; prefer it over the fixed formula when present.

While in this code: wrap the `r.json()` calls in `try/except ValueError` (or `json.JSONDecodeError`) as shown — currently an unhandled non-JSON 200 response (e.g. a WAF challenge page served with status 200) would raise an uncaught exception and crash the whole scrape run, not just the PCCG portion.

### 11.2 Add a run-level circuit breaker, not just a per-request one

`scrape_category()` already tracks `consecutive_failures` across batches and increases the inter-batch delay, but never actually stops — it will keep grinding through every batch in the watchlist at up to `ALGOLIA_BACKOFF_MAX_SECONDS` delay each, even when PCCG has been fully blocking all day. With the 11.1 fix in place this at least terminates instead of hanging, but it still wastes a full watchlist's worth of retries before giving up.

Add a hard cap: if `consecutive_failures` reaches a threshold (e.g. 3), stop processing remaining batches for that category entirely, log a clear one-line reason, and return whatever was matched so far. Same idea applies across categories in `main()` — if CPU category aborts via circuit breaker, still attempt GPU (they're independent Algolia queries and a block on one doesn't necessarily mean the other is blocked at that exact moment), but if GPU also trips the breaker, exit `main()` promptly rather than continuing to loop.

### 11.3 Persist a short cooldown so retries don't immediately re-trip the breaker

When the circuit breaker trips (11.2), write a small state file, e.g. `data/pccg_cooldown.json`:

```json
{"tripped_at": "2026-08-16T06:12:00+10:00", "reason": "429 circuit breaker"}
```

On scraper start, check this file first. If present and within a cooldown window (start with `TRACKAROO_PCCG_COOLDOWN_HOURS`, default 4), skip scraping entirely, log why, and exit cleanly (exit code 0, not an error — this is expected/handled behavior, not a crash). Clear/ignore the file once a scrape succeeds. This stops a scheduled retry (see 11.4) from immediately hammering PCCG again within minutes of a block and makes the block-and-recover cycle visible in logs without anyone needing to check in on it.

### 11.4 Turn "want me to retry later?" into a scheduled retry, not a manual decision

`run_daily.py --pccg` already exists and already does the right thing (re-scrape + ingest PCCG only, leaving Scorptec's already-ingested data untouched). What's missing is *automatically trying again later in the day* instead of that being a manual call each time it happens.

Add a second scheduled job (cron/systemd timer, same mechanism as the daily run and the weekly spec sync) that runs `python run_daily.py --pccg` a few hours after the main daily run — e.g. main run at 06:00, retry attempts at 12:00 and 18:00. Because of 11.1–11.3, each attempt is now cheap and safe to run unconditionally: if PCCG is healthy, it scrapes and ingests normally (idempotent — matches the "never delete, ingestion is idempotent" principle already in place); if still blocked, it fails fast, respects the cooldown file, and exits quietly. This removes the need for the "retry now or leave it?" judgment call — it either resolves itself within the day or, if it's still failing after the last scheduled retry, that's the point where it's worth a human look (e.g. surfaced in the health check summary — see 11.5).

### 11.5 Make partial-day state visible in health checks, not just in the scrape log

`health_checks.py` already checks DB freshness and match-count anomalies. Add a check (or extend `check_db_freshness`) that reports, per retailer, whether today's date has a snapshot yet — so "Scorptec ingested, PCCG missing for today" shows up as a named, expected-shape warning in the regular health check output rather than something only visible by reading scrape logs.

### 11.6 Lower-priority tuning, worth doing at the same time since the code's already open

- No delay currently exists between the CPU and GPU category passes inside `scraper/pccg.py`'s `main()` (`for category in ["cpu", "gpu"]:` loops straight through). Add a short delay between them — reuses `BATCH_DELAY` or a new small constant — since both hit the same Algolia index from the same IP back-to-back.
- Consider lowering `TRACKAROO_BATCH_SIZE` (default 16) and/or raising `TRACKAROO_BATCH_DELAY` (default 1.0s) as tunable knobs specifically for the scheduled retry runs (11.4), even if the main daily run keeps current values — a retry attempt is a good place to be extra conservative.
- Log status code categories distinctly: 429 (rate limit) vs 401/403 (would indicate the embedded read-only Algolia App ID/API key has been rotated by PCCG, a different problem entirely that no amount of backoff fixes). Right now both would just show up as "API error" — worth being able to tell them apart at a glance in logs.

### 11.7 What NOT to do here

- Don't add proxies, IP rotation, or anything designed to evade detection — that crosses from "being a polite, resilient client" into the kind of thing the project already explicitly avoided when it dropped Mwave over robots.txt. The fixes above are all about the scraper behaving correctly and giving up gracefully, not about getting around a block.
- Don't change `fetch_test.py` (Scorptec) as part of this — it isn't exhibiting this problem and isn't Algolia-based; keep this scoped to `scraper/pccg.py`, `config.py`, and the small additions to `run_daily.py`/`health_checks.py` described above.

## 11. Open questions for Dennis (do not guess on these — ask)

1. Final CPU source: felixsteinke/cpu-spec-dataset (recommended) vs. Intel+AMD JSON pair — confirm after inspecting felixsteinke's CSV schema.
2. Fuzzy-match threshold: start at 90, but should be tuned against real false-positive/false-negative examples from the actual watchlist before considering this "done."
3. Whether AIB-partner cards should each get their own `specs` row (all sharing the same reference-chip specs) or whether specs should live only at a chip/reference level with the UI resolving "which specs to show" for a partner card at render time. Recommendation: latter (one `specs` row per reference chip, not per AIB variant) — simpler, avoids duplicating identical data ~50 times per generation — but confirm before building, since it affects the matching target in §4.2.
4. Circuit-breaker and cooldown thresholds for §10.2/§10.3 (consecutive-failure count before aborting, cooldown window length before an automatic retry is allowed to try again) — the values in this doc (3 failures, 4-hour cooldown) are starting points, not settled numbers. Tune based on how PCCG's blocking actually behaves once the fix is live and a few real block-and-recover cycles have been observed.
