# OzBargain Deals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poll OzBargain's GPU and CPU RSS feeds every 2 hours, match deals to tracked products, alert Discord when a live deal beats today's best in-stock price, and show the deals on the product page and /deals.

**Architecture:**
- `ozbargain.py` is a single-poll script. It fetches 2 tag feeds, parses them with stdlib XML and matches titles with the existing `scraper.chip_key.Matcher` (built from tracked `products` rows). It upserts into a new `ozb_deals` table, logs to `ozb_polls`, and sends at most 5 Discord alerts through `notify_discord.send_embed`.
- An `ozb_loop` in `deploy/entrypoint-single.sh` runs it on the poll hours.
- The web reads `ozb_deals` through a new `queries/ozbargain.ts`.

**Tech Stack:**
- Python 3.12: requests, sqlite3, xml.etree, pytest.
- SvelteKit 2 / Svelte 5 with TypeScript, better-sqlite3, vitest, Playwright + axe, `@lucide/svelte`.

**Spec:** `docs/superpowers/specs/2026-10-03-ozbargain-design.md`

## Global Constraints

- **Feeds and requests:**
  - Feeds: `https://www.ozbargain.com.au/tag/video-card/feed` (gpu) and `https://www.ozbargain.com.au/tag/cpu/feed` (cpu).
  - Exactly 2 GETs per poll, with no retries inside a poll, `timeout=10`, and header `User-Agent: Trackaroo/1.0 (+https://github.com/2ndtlmining/Trackaroo)`.
  - Never request or store a `/goto/` URL. The stored deal URL is the `/node/<id>` page.
- **Poll hours:** `OZB_POLL_HOURS` defaults to `07,09,11,13,15,17,19,21,23` (Australia/Melbourne, the container TZ). `OZB_ENABLED=0` disables the loop, and it never starts under `SKIP_PIPELINE=1`.
- **Tables:** two additive tables, `ozb_deals` and `ozb_polls`, in `migrate.py` + `db/schema.sql`, with the DDL exactly as in spec §6. There is no change to `retailer_listings`, `price_snapshots`, the JSON mirror or backups.
- **Retention:** `ozb_deals` rows with `last_seen_at` older than 180 days are deleted, and `ozb_polls` rows older than 30 days.
- **Alert rule:** a deal alerts when all of these hold:
  - `product_id` is not null, `alerted_at` is null, and `expired = 0`;
  - `starts_at` is null or not in the future;
  - `price_aud` is not null;
  - `votes_pos − votes_neg ≥ 0`;
  - `price_aud < best in-stock price on the product's latest snapshot date` (non-bundle listings). If there is no in-stock price, it alerts.

  Sending:
  - Webhook `DISCORD_WEBHOOK_URL`. Set `alerted_at` only after a successful send.
  - At most 5 per poll, ordered by `price_aud / best` ascending, with no-best last.
  - Product links use `TRACKAROO_PUBLIC_BASE_URL`.
- **Health:** `check_ozbargain` is WARNING-only (no `ok` poll in 24 h). It is silent when the table is missing or `OZB_ENABLED=0`, and never returns ERROR.
- **Tests:** never touch the network. conftest blocks sockets; mock `ozbargain.requests.get`. Add an autouse guard patching `ozbargain.DB_PATH` to tmp.
- **Web text and design:**
  - No emojis in `web/src` (`noEmoji.test.ts`).
  - Icons come from `@lucide/svelte`, imported per file (`@lucide/svelte/icons/<name>`), always `aria-hidden="true"`.
  - Existing colour tokens only. `contrast.test.ts` and axe must pass in both themes.
  - No `toLocale*`: use `$lib/formats`.
- **Repo rules:**
  - Server queries live in `web/src/lib/server/queries/*`, exported through the `$lib/server/repos` barrel. DTO types live in `$lib/models`.
  - Client code never imports `$lib/server`. Files are capped at 350 lines (`test/boundaries.test.ts`).
  - Never open `db/trackaroo.db`. Never run `docker compose up` in the dev copy.
- **Gate:** after every task, `python -m pytest -q`, then `npm run check` 0/0, `npm test` and `npm run test:e2e` from `web/`, all green.
- **Changelog:** add a line under `## Unreleased` in `CHANGELOG.md` (Task 6).

## Review Focus

1. **A feed item with odd fields:**
   - no `<ozb:meta>`;
   - `expiry` without a timezone;
   - a title with two prices ("$1,099 (was $1,299)");
   - a price with cents ("$899.95");
   - "% off" and no `$`;
   - "@" inside a product name.

   The first `$` amount wins, missing attributes become null or 0, and nothing raises. Task 1 tests each one.
2. **One feed down, the other up** (HTTP 403, a timeout, or HTML instead of XML): the poll is still `ok` with the items from the good feed, and logs a WARNING for the bad one. If both fail, the poll is not ok and no alert is sent. Task 2 tests this.
3. **An 8 GB vs 16 GB card posted without the VRAM** while both variants are tracked: the deal is stored unmatched and never alerts. A bundle or prebuilt PC ("Gaming PC with RTX 5070") is skipped entirely. Task 2 tests this.
4. **Discord down, or no webhook:** nothing is marked alerted, the next poll retries, and the poll itself still succeeds. Task 3 tests this.
5. **First deploy, no tables or polls yet:** the product page hides the panel, /deals has no chips, `check_ozbargain` is silent, and nothing throws. Tasks 4 and 5 test this.

## File Structure

| File | Responsibility |
|---|---|
| `ozbargain.py` (new) | `parse_feed`, `parse_price`, `parse_retailer`, `poll`, `run`, CLI (`--dry-run`) |
| `ozbargain_alerts.py` (new) | `best_in_stock`, `alert_candidates`, `build_embed`, `send_alerts` |
| `migrate.py`, `db/schema.sql` | `ozb_deals`, `ozb_polls` |
| `health_checks.py`, `run_daily.py` | `check_ozbargain`, registered in `_db_checks()` |
| `deploy/entrypoint-single.sh` | `ozb_loop` |
| `unit_testing/fixtures/ozbargain_video_card_feed.xml`, `ozbargain_cpu_feed.xml` (new) | Saved feed fixtures |
| `unit_testing/test_ozbargain.py`, `test_ozbargain_alerts.py` (new) | Python tests |
| `web/src/lib/server/queries/ozbargain.ts` (new) | `getOzbDeals`, `getLiveOzbDealByProduct` |
| `web/src/lib/components/OzbDealsPanel.svelte` (new) | Product-page panel |
| Product page loader and page, /deals loader and page, `ProductRow`/deal row | Wiring and the chip |
| `web/e2e/seed.mjs`, `web/e2e/app.spec.ts`, `web/e2e/a11y.spec.ts` | Seed deals; e2e |

---

### Task 1: Feed parser (pure Python)

**Files:**
- Create: `ozbargain.py` (parsing functions only in this task), `unit_testing/fixtures/ozbargain_video_card_feed.xml`, `unit_testing/fixtures/ozbargain_cpu_feed.xml`, `unit_testing/test_ozbargain.py`

**Interfaces:**
- Produces:
```python
FEEDS: Tuple[Tuple[str, str], ...] = (
    ("gpu", "https://www.ozbargain.com.au/tag/video-card/feed"),
    ("cpu", "https://www.ozbargain.com.au/tag/cpu/feed"),
)
USER_AGENT = "Trackaroo/1.0 (+https://github.com/2ndtlmining/Trackaroo)"

@dataclass
class FeedItem:
    node_id: int
    category: str            # 'gpu' | 'cpu'
    title: str
    url: str                 # https://www.ozbargain.com.au/node/<id>
    price_aud: Optional[float]
    retailer: Optional[str]
    votes_pos: int
    votes_neg: int
    comment_count: int
    posted_at: Optional[str]   # ISO 8601 with offset
    starts_at: Optional[str]
    expires_at: Optional[str]
    expired: bool
    product_slugs: List[str]   # from <category domain=".../product/<slug>">

def parse_price(title: str) -> Optional[float]
def parse_retailer(title: str) -> Optional[str]
def parse_feed(xml_text: str, category: str, now: datetime) -> List[FeedItem]
```

- [ ] **Step 1: Fixtures.** Write two RSS 2.0 files in OzBargain's layout: `<rss version="2.0" xmlns:ozb="https://www.ozbargain.com.au">` containing a `<channel>`. Each `<item>` has `<title>`, `<link>https://www.ozbargain.com.au/node/N</link>`, `<pubDate>` (RFC 822, e.g. `Fri, 03 Oct 2026 09:12:00 +1000`), `<guid isPermaLink="false">N at https://www.ozbargain.com.au</guid>`, `<category domain="https://www.ozbargain.com.au/cat/computing">Computing</category>`, optional `<category domain="https://www.ozbargain.com.au/product/<slug>">…</category>`, and `<ozb:meta comment-count=… click-count=… votes-pos=… votes-neg=… expiry=… starting=… url="https://www.ozbargain.com.au/goto/N"/>`. Expired items also carry `<ozb:title-msg type="expired">expired</ozb:title-msg>`.

  The video-card fixture must contain at least these items:
  - 912001 `[Pre Order] ASUS Prime GeForce RTX 5070 Ti 16GB $1,099 @ Mwave`: votes 42/1, expiry tomorrow, product slug `nvidia-geforce-rtx-5070-ti`.
  - 912002 `MSI GeForce RTX 5060 Ti $529 (Was $649) @ Centre Com`: no VRAM in the title, votes 10/0.
  - 912003 `Gigabyte Radeon RX 9070 XT 16GB $949.95 Delivered @ Amazon AU`: carries `<ozb:title-msg type="expired">`.
  - 912004 `Gaming PC with RTX 5070 $1,999 @ JW Computers`: a prebuilt.
  - 912005 `10% off Graphics Cards @ Scorptec`: no `$`.
  - 912006 `Sapphire Pulse RX 9060 XT 16GB $579 @ PLE`: votes 2/7 (net negative).
  - 912007 `PNY RTX 5070 12GB $899 @ Amazon AU`: `starting` is in the future.
  - 912008: has no `<ozb:meta>` element at all, and title `Zotac RTX 5080 16GB $1,599 @ Umart`.

  The cpu fixture holds 3 items:
  - `AMD Ryzen 7 9800X3D $689 @ PCCG`;
  - `Intel Core Ultra 5 245K $399 @ Amazon AU`;
  - an expired one.

  Use fixed dates around `2026-10-03`. Tests pass `now = datetime(2026, 10, 3, 12, 0, tzinfo=ZoneInfo('Australia/Melbourne'))`. If `zoneinfo` lacks tzdata on Windows, use a fixed `+10:00` offset.
- [ ] **Step 2: Failing tests** (`unit_testing/test_ozbargain.py`):
  - **`parse_price`:**
    - `"$1,099 @ Mwave"` gives 1099.0 and `"$949.95 Delivered"` gives 949.95;
    - `"$529 (Was $649)"` gives 529.0, because the first amount wins;
    - `"10% off"` gives None, and `"$0"` gives None (a non-positive price is not a price).
  - **`parse_retailer`:**
    - gives the text after the last `" @ "`, trimmed, e.g. `"Mwave"`;
    - gives None with no `" @ "`;
    - `"Foo@Bar $5"` (no spaces) gives None.
  - **`parse_feed` on the gpu fixture:**
    - 8 items, with the correct node ids and the url `https://www.ozbargain.com.au/node/912001`;
    - votes and comment counts are read;
    - 912003 is `expired=True`;
    - an `expiry` in the past also gives `expired=True`;
    - 912001 has `product_slugs == ['nvidia-geforce-rtx-5070-ti']`;
    - 912008 (no meta) has votes 0/0 and expiry None, and does not raise;
    - no field contains `/goto/`.
  - **Malformed XML** (`"<html>blocked</html>"` or truncated XML) raises `ValueError`, with a message naming the category.
- [ ] **Step 3: Run** `python -m pytest unit_testing/test_ozbargain.py -q` and expect FAIL.
- [ ] **Step 4: Implement** in `ozbargain.py`:
  - Parse with `xml.etree.ElementTree.fromstring`, and wrap `ParseError` as `ValueError(f"{category} feed: {e}")`.
  - Find the `meta` and `title-msg` children namespace-agnostically: compare `el.tag.rsplit('}', 1)[-1]`.
  - Take the node id from `<link>` with the regex `/node/(\d+)`, falling back to a leading integer in `<guid>`. Skip items with neither.
  - Parse `pubDate` with `email.utils.parsedate_to_datetime(...).isoformat()`.
  - Store `expiry` and `starting` as given (ISO). Mark `expired` when a `title-msg` has `type` in `{"expired", "sold out", "out of stock"}` (case-insensitive), or when `datetime.fromisoformat(expiry) < now`. Treat a naive expiry as Melbourne time (+10:00).
  - Price regex: `\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?`.
  - Retailer: `title.rsplit(" @ ", 1)[1].strip()` when present.
  - Product slugs: from `category` elements whose `domain` contains `/product/`, taking the last path segment.
- [ ] **Step 5: Run** the test file and expect GREEN. Run the full `python -m pytest -q`.
- [ ] **Step 6: Commit**: `feat(ozb): OzBargain RSS feed parser with saved fixtures (#34)`.

---

### Task 2: Poll — fetch, match, store

**Files:**
- Modify: `ozbargain.py`, `migrate.py`, `db/schema.sql`, `unit_testing/conftest.py`, `unit_testing/test_ozbargain.py`, `unit_testing/test_migrate.py`

**Interfaces:**
- Consumes: Task 1's `FEEDS`, `USER_AGENT`, `parse_feed` and `FeedItem`.
- Produces:
```python
DB_PATH: Path  # module global, resolved at call time; = config DB path
def build_matchers(conn) -> Dict[str, Tuple[Matcher, List[dict]]]  # per category, from tracked products rows
def match_item(item: FeedItem, matchers) -> Optional[int]          # product_id or None
def upsert_items(conn, items: Sequence[FeedItem], product_ids: Sequence[Optional[int]], seen_at: str) -> None
def prune(conn, now: datetime) -> None
def poll(conn, now: datetime, dry_run: bool = False) -> Dict[str, Any]  # {'ok': bool, 'items': int, 'matched': int, 'errors': [str]}
def run(db_path: Optional[Path] = None, dry_run: bool = False, now: Optional[datetime] = None) -> Dict[str, Any]
migrate.migrate_add_ozbargain_tables(conn, dry_run=False)
```
- `run()` connects, calls the migration, then `poll`, then `prune`, writes one `ozb_polls` row (not on dry run), and logs a summary. (Task 3 adds the `send_alerts` call; do not add it here.)
- CLI: `python ozbargain.py [--dry-run]`. It calls `config.setup_logging()` and prints the summary. In dry-run mode it also prints each matched item as `node_id product title price` and writes nothing.

- [ ] **Step 1: Failing tests:**
  - **Migration:** `migrate_add_ozbargain_tables` is idempotent. `schema.sql` creates both tables with the spec §6 columns and the `idx_ozb_deals_product` index.
  - **`build_matchers` / `match_item`:** use a temp DB with tracked products RTX 5070 Ti 16GB, RTX 5060 Ti 8GB, RTX 5060 Ti 16GB, RTX 5080 16GB, RTX 5070 12GB, RX 9060 XT 16GB and Ryzen 7 9800X3D, plus one untracked product.
    - 912001 gives RTX 5070 Ti.
    - 912002 (5060 Ti, no VRAM, two variants tracked) gives None.
    - 912004 (prebuilt) gives None. Exclusion uses `discover_rules.is_excluded_title`.
    - 912008 gives RTX 5080.
    - The cpu 9800X3D item gives Ryzen 7 9800X3D.
    - An untracked product never matches.
    - The slug fallback: an item whose title has no chip but whose slug is `nvidia-geforce-rtx-5070-ti` gives RTX 5070 Ti.
  - **`upsert_items`:**
    - two polls of the same item give one row;
    - votes, `expired` and `last_seen_at` refresh;
    - `first_seen_at` and `alerted_at` are kept;
    - a non-null `product_id` is not overwritten by a later null.
  - **`prune`:** a deal last seen 181 days ago is deleted; one seen 179 days ago is kept. A poll row 31 days old is deleted.
  - **`run()` with mocked `ozbargain.requests.get`:**
    - **Budget:** exactly 2 GETs, to the two `FEEDS` URLs, with `timeout=10` and the User-Agent header.
    - **Both ok:** items stored, one `ozb_polls` row with `ok=1` and `items=11`.
    - **One feed raising, or returning 403, or returning HTML:** `ok=1`, the other feed's items are stored, and a WARNING is logged naming the category.
    - **Both failing:** `ok=0`, `error` set, no exception, and no alert attempted.
    - **Dry run:** no rows written, not even `ozb_polls`.
    - `DB_PATH` is resolved at call time.
  - **conftest:** an autouse guard sets `ozbargain.DB_PATH` to `tmp_path / "ozb-guard.db"`, mirroring the discovery guard.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - `build_matchers` selects `id, category, brand, model, vram_gb FROM products WHERE tracked = 1` and builds one `Matcher` per category from dicts with the keys `Matcher` reads (`model`, `category`, `vram_gb`). Keep the rows list so an index maps to `id`.
  - `match_item` skips when `is_excluded_title(item.title)`. It tries `matcher.resolve(item.title, item.category)`, then each slug (`slug.replace('-', ' ')`) with `extra_text=item.title`, so the VRAM in the title still applies.
  - Upsert with `INSERT ... ON CONFLICT(node_id) DO UPDATE SET votes_pos=excluded.votes_pos, ..., product_id=COALESCE(ozb_deals.product_id, excluded.product_id), last_seen_at=excluded.last_seen_at`.
  - Times are ISO strings from `now.isoformat(timespec='seconds')`.
  - Keep `ozbargain.py` ≤ 350 lines.
- [ ] **Step 4: Run** the full pytest. Green.
- [ ] **Step 5: Commit**: `feat(ozb): poll the two tag feeds, match to tracked products, store in ozb_deals (#34)`.

---

### Task 3: Discord alerts

**Files:**
- Create: `ozbargain_alerts.py`, `unit_testing/test_ozbargain_alerts.py`
- Modify: `ozbargain.py` (call `send_alerts` at the end of a non-dry-run `run()`, after a poll with `ok`)

**Interfaces:**
- Consumes: the `ozb_deals` table (Task 2), and `notify_discord.send_embed(webhook_url, embed) -> bool`, `notify_discord.load_dotenv()` and `notify_discord.format_aud(value)`.
- Produces:
```python
MAX_ALERTS_PER_POLL = 5
def best_in_stock(conn, product_id: int) -> Optional[Tuple[float, str]]  # (price, retailer) on the product's latest snapshot date, in-stock, non-bundle
def alert_candidates(conn, now: datetime) -> List[dict]   # ordered, capped at MAX_ALERTS_PER_POLL
def build_embed(candidate: dict, base_url: str) -> dict
def send_alerts(conn, now: datetime) -> int                # number sent
```

- [ ] **Step 1: Failing tests:**
  - **`best_in_stock`:**
    - gives the min in-stock price on the product's latest `snapshot_date` across retailers;
    - ignores out-of-stock rows and older dates;
    - ignores bundle listings (the same rules as the web's `notBundle`: `variant_name` contains bundle/combo, or the URL contains bundle/`bdl-`);
    - gives None when nothing is in stock.
  - **`alert_candidates` (one test per rule):**
    - a qualifying deal is included;
    - price equal to best is excluded; price one cent below is included;
    - net-negative votes are excluded; net zero is included;
    - expired, a future `starts_at`, a null price, a null `product_id`, or an already-set `alerted_at` excludes the deal;
    - with no in-stock best the deal is included and sorts last;
    - with 7 qualifying deals, 5 come back, ordered by `price/best` ascending.
  - **`send_alerts`:**
    - with `DISCORD_WEBHOOK_URL` unset it returns 0 and `alerted_at` stays null;
    - with `send_embed` mocked True it sets `alerted_at` for each sent deal and returns the count;
    - with `send_embed` returning False, `alerted_at` stays null and the next call retries;
    - a send that raises is caught and logged, and the rest still go.
  - **`build_embed`:**
    - the title is `"OzBargain: <brand model[ vram]GB> $1,099 at Mwave"`;
    - the description includes `"Our best today: $1,199 at PCCG"` (or `"Not in stock at our retailers"`) and `"+42 / −1 votes"`;
    - links to the node URL and to `<base>/product/<id>` (omitted when there is no base URL);
    - no emoji, and no `/goto/` anywhere.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - The product display name comes from `products` (`brand`, `model`, plus `vram_gb` for GPUs as `" 16GB"`).
  - Use `notify_discord.load_dotenv()` and read `DISCORD_WEBHOOK_URL` and `TRACKAROO_PUBLIC_BASE_URL` at call time.
  - Wire it into `ozbargain.run()`, and add a test there: a successful poll calls `send_alerts`, while a failed poll or a dry run does not.
- [ ] **Step 4: Run** the full pytest. Green.
- [ ] **Step 5: Commit**: `feat(ozb): Discord alert when a live OzBargain deal beats today's best in-stock price (#34)`.

---

### Task 4: Schedule and health

**Files:**
- Modify: `deploy/entrypoint-single.sh`, `health_checks.py`, `run_daily.py`, `.env.example`, `docker-compose.yml` (only if env passthrough is listed explicitly), `unit_testing/test_health_checks.py`, `unit_testing/test_run_daily_resilience.py`, `unit_testing/test_entrypoint*.py` or `test_shell_scripts.py` (whichever already checks the entrypoint loops)

**Interfaces:**
- Consumes: the `ozb_polls` table.
- Produces: `health_checks.check_ozbargain(db_path, now=None) -> list[CheckResult]`, and an `ozb_loop` in the entrypoint.

- [ ] **Step 1: Failing tests:**
  - **`check_ozbargain`:**
    - OK when an `ok` poll is 3 h old;
    - WARNING when the newest `ok` poll is 25 h old, or when every row is `ok=0`;
    - empty list or OK (match the repo's existing convention for "nothing to say") when the table is missing;
    - silent when `OZB_ENABLED=0` (monkeypatch the env);
    - never ERROR, including on an unreadable DB, which gives WARNING.
  - **`run_daily._db_checks()`** includes `check_ozbargain`.
  - **Entrypoint** (a text-level test, as the existing entrypoint tests do):
    - `ozb_loop` is defined and started in the background only on the path where the scheduler starts, i.e. after the `SKIP_PIPELINE` early exit;
    - it reads `OZB_POLL_HOURS` with the default `07,09,11,13,15,17,19,21,23`;
    - it honours `OZB_ENABLED=0`;
    - it runs `python ozbargain.py`;
    - it guards against running twice in the same hour (a `last_run` of date+hour);
    - the file stays LF.
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.**
  - The loop follows `staleness_loop`:
```sh
: "${OZB_ENABLED:=1}"
: "${OZB_POLL_HOURS:=07,09,11,13,15,17,19,21,23}"
run_ozbargain() {
    log "Polling OzBargain..."
    python ozbargain.py && log "OzBargain poll finished." || log "OzBargain poll finished with errors (next poll retries)."
}
ozb_loop() {
    last_run=""
    while true; do
        hour=$(date '+%H')
        stamp="$(date '+%Y-%m-%d')T$hour"
        case ",$OZB_POLL_HOURS," in
            *",$hour,"*) if [ "$last_run" != "$stamp" ]; then run_ozbargain; last_run="$stamp"; fi ;;
        esac
        sleep 600
    done
}
```
  - Start it with `[ "$OZB_ENABLED" = "1" ] && ozb_loop &`, next to where `staleness_loop &` starts. `sleep 600` (10 min) keeps the poll near the top of the hour, and the `last_run` guard prevents repeats.
  - Document `OZB_ENABLED` and `OZB_POLL_HOURS` in `.env.example`.
  - Register `check_ozbargain` in `_db_checks()`.
- [ ] **Step 4: Run** the full pytest. Green. If `Dockerfile`/`deploy/` changed, build and boot the image offline per CLAUDE.md (`--network none -e SKIP_PIPELINE=1`) and confirm it is healthy. The loop must not run under `SKIP_PIPELINE`.
- [ ] **Step 5: Commit**: `feat(ozb): 2-hourly poll loop in the container, WARNING-only health check (#34)`.

---

### Task 5: Web — product-page panel and /deals chip

**Files:**
- Create: `web/src/lib/server/queries/ozbargain.ts`, `web/src/lib/components/OzbDealsPanel.svelte`, `web/test/ozbargain.test.ts`
- Modify: `web/src/lib/server/repos.ts` (barrel), `web/src/lib/models.ts` (DTO), `web/src/routes/product/[id]/+page.server.ts` and `+page.svelte`, `web/src/routes/deals/+page.server.ts` and `+page.svelte` (and the deal row component, if rows render elsewhere), `web/e2e/seed.mjs`, `web/e2e/app.spec.ts`, `web/e2e/a11y.spec.ts` (only if a new page is needed; the product and deals pages are already in the list), `web/test/loaders.test.ts`

**Interfaces:**
- Consumes: the `ozb_deals` table.
- Produces:
```ts
// $lib/models
export interface OzbDeal { nodeId: number; title: string; url: string; priceAud: number | null; retailer: string | null; votesPos: number; votesNeg: number; postedAt: string | null; expired: boolean; }
// queries/ozbargain.ts
export function getOzbDeals(db: DB, productId: number, now: Date): { live: OzbDeal[]; expired: OzbDeal[] } // live: newest first, max 5; expired: last 30 days by last_seen_at, max 10; empty when the table is missing
export function getLiveOzbDealByProduct(db: DB): Map<number, OzbDeal> // cheapest live priced deal per product; empty map when the table is missing
```
- "Live" means `expired = 0 AND (starts_at IS NULL OR starts_at <= now)`.

- [ ] **Step 1: Failing tests.**
  - **vitest (`web/test/ozbargain.test.ts`, on an in-memory better-sqlite3 DB built from `db/schema.sql`):**
    - live/expired split, the cap of 5, newest first;
    - the 30-day expired window;
    - the future `starts_at` excluded from live;
    - the missing table gives empty results with no throw;
    - `getLiveOzbDealByProduct` picks the cheapest priced live deal per product and ignores null-price deals.
  - **`loaders.test.ts`:**
    - the product loader returns `ozb: { live, expired }` (empty on the seeded DB without deals);
    - the deals loader returns, per row, `ozb: OzbDeal | null`.
  - **e2e:** seed three `ozb_deals` rows in `web/e2e/seed.mjs` for the fixture product `E2E Deal Demo GPU`: one live and below that product's best price, one live and above it, and one expired (`last_seen_at` today). Create the table with the DDL from `db/schema.sql` if the seed's schema load does not already include it. Then:
    - `/product/<E2E Deal Demo GPU id>` (use `productIdByModel`) shows the heading "OzBargain deals" with 2 rows. The below-best row reads "Below our best".
    - Each "View deal" link has the node URL with `target="_blank"`, and none contains `/goto/`.
    - The "Show expired (1)" toggle reveals 1 more row labelled "Expired".
    - A product with no deals has no "OzBargain deals" heading.
    - `/deals` shows an "OzBargain" chip on that product's row, linking to the cheaper live deal.
    - axe stays green (the product page is already in `a11y.spec.ts`; add the fixture product's page if `/product/1` is not that product).
- [ ] **Step 2: Run** and expect FAIL.
- [ ] **Step 3: Implement.** **Load the `frontend-design` skill first.**
  - **`OzbDealsPanel.svelte`:**
    - a section with heading "OzBargain deals" and a one-line muted note: "Community-posted deals from OzBargain, checked every 2 hours. Prices are as posted.";
    - a list of rows. Each row has the price in tabular numerals (`formatAud`, or "Price in post"), the retailer, the votes `+42 / −1` (U+2212 minus), the age via `$lib/formats` (add a small `formatAgo(iso, now)` if none exists, with tests), and a "View deal" link with `ArrowUpRight`;
    - below-best rows use the success tone with the text "Below our best";
    - the expired toggle is a `<button aria-expanded aria-controls>`;
    - it renders nothing when `live` and `expired` are both empty.
  - Place it on the product page below the buying-signals panel. The page's "best in-stock today" value already exists in the page data (the headline price); compare `priceAud < best`.
  - **/deals chip:** a small pill "OzBargain $1,099" with the Lucide `Tag` icon, linking to the deal node (`target=_blank rel=noopener`). Use existing chip and badge styles.
  - Keep every file at or under 350 lines.
- [ ] **Step 4: Run** `npm run check` 0/0, `npm test` and `npm run test:e2e` (with axe). Take light and dark screenshots at desktop and 390 px of the fixture product page into the system temp dir, and describe them in the report.
- [ ] **Step 5: Commit**: `feat(web): OzBargain deals panel on the product page and a chip on /deals (#34)`.

---

### Task 6: Docs, changelog and gate

- [ ] **README:** an "OzBargain deals" section covering:
  - what is polled and when (`OZB_POLL_HOURS`, `OZB_ENABLED`);
  - the 18-requests-a-day budget, and RSS only (no `/goto/`);
  - the alert rule;
  - `docker compose exec trackaroo python ozbargain.py --dry-run`;
  - that the deals never enter price history.
- [ ] **CLAUDE.md:** one Pipeline-conventions line: `ozbargain.py` runs on its own 2-hourly loop, it is best-effort, `check_ozbargain` is WARNING-only, and there is a 2-GET budget pinned by test. Update the test counts.
- [ ] **`docs/ARCHITECTURE.md`** decision log: "OzBargain posts are a separate table, never price history; RSS tag feeds only."
- [ ] **CHANGELOG.md:** under `## Unreleased` → `### Added`, add the line "OzBargain deals on product pages and /deals, with a Discord alert when a deal beats our best in-stock price (#34)."
- [ ] **STATUS.md:** a dated bullet.
- [ ] **Full gate:** pytest, check 0/0, vitest, Playwright and `npm run build`, plus the offline image boot (the entrypoint changed). Commit: `docs: OzBargain deals (#34)`.
