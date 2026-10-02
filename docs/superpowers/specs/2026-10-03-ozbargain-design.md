# OzBargain deals: design

**Date:** 2026-10-03 · **Issue:** #34 · **Sub-project 4 of 6**
**Status:** design approved in conversation 3-Oct-2026, awaiting written-spec review

## 1. Purpose

Tell the owner quickly when an AU deal on a tracked part beats the best price Trackaroo can see. OzBargain is where flash sales, coupon codes and deals at retailers we do not scrape (Centre Com, Mwave, JW, Amazon AU, eBay) appear first, and its votes are a quality signal. Reading its RSS feeds adds this coverage with no retailer scraping and no WAF risk.

### Owner decisions (3-Oct-2026)
- **Alerts are the point.** A Discord alert fires when a live deal beats today's best in-stock price at our retailers. The product-page panel and the /deals chip are for reference.
- **Poll every 2 hours from 07:00 to 23:00 Melbourne**, separately from the 04:00 scrape. That is 9 polls × 2 feeds = **18 requests a day**, inside the issue's ~20/day budget.
- **Alert rule:** the deal must beat today's cheapest in-stock price at Scorptec/PCCG/Umart, and must not be net-negative on votes. Each deal alerts once.

### Success criteria
- A matching live deal below today's best in-stock price reaches Discord within about 2 hours of being posted, and only once.
- The product page shows live OzBargain deals, with expired deals hidden by default.
- /deals marks items that have a live OzBargain deal.
- At most 18 feed requests a day, with an honest User-Agent, and only RSS feeds (`robots.txt` disallows `/goto/`, `/api/`, `/ozbapi/` and `/search/`).
- Price history, charts, deals maths and backups are unchanged.
- The four suites are green, axe stays green in both themes, and the parser is tested against a saved feed fixture.

## 2. Data safety
- Two additive tables, `ozb_deals` and `ozb_polls`, created by `migrate.py` (and `db/schema.sql`) on startup, like the earlier bookkeeping tables.
- OzBargain posts **never** go into `listings` or `price_snapshots`. They are community posts, not snapshots, and are not mirrored to `data/` JSON.
- The web only reads. There is never a fetch at request time.
- All tests mock HTTP. The conftest network guard stays as it is.

## 3. Out of scope
- Per-product feeds (`/product/<slug>/feed`). The tag feeds already carry an exact product tag per item, and adding these feeds would break the budget.
- Showing unmatched deals (ambiguous VRAM, untracked parts). They are stored; they could feed /discover later.
- Following `/goto/` links, or reading OzBargain pages beyond the RSS feeds.
- Alerts based on the all-time low, or a digest of every deal.

## 4. Fetching (`ozbargain.py`)
- **One poll** = two GETs: `https://www.ozbargain.com.au/tag/video-card/feed` (category `gpu`) and `https://www.ozbargain.com.au/tag/cpu/feed` (category `cpu`). Each has a 10 s timeout and the header `User-Agent: Trackaroo/1.0 (+https://github.com/2ndtlmining/Trackaroo)`. There are no retries inside a poll; the next poll is the retry.
- **Parsing** uses `xml.etree.ElementTree` (stdlib), with the `ozb` namespace read from the feed. Per `<item>`:
  - **Node id:** from `<link>` or `<guid>`, e.g. `https://www.ozbargain.com.au/node/912345` gives `912345`.
  - **Title**, plus `link`, the node page, stored as the deal URL. A `url=` attribute pointing at `/goto/` is never stored or followed.
  - **`<ozb:meta>` attributes:** `votes-pos`, `votes-neg`, `comment-count`, `expiry`, `starting`. Missing attributes become null or 0.
  - **Expired:** `<ozb:title-msg type="expired">` present (also `type="sold out"`), or `expiry` in the past.
  - **Product tags:** `<category domain="https://www.ozbargain.com.au/product/<slug>">`, keeping each slug.
  - **Posted at:** from `<pubDate>`.
- **Price:** the first `$` amount in the title (`$1,099`, `$899.95`), as a float. When a title has several, the first is taken. A title with "% off" and no `$` gives null.
- **Retailer:** the text after " @ " in the title (OzBargain's convention, e.g. "... $1,099 @ Mwave"), trimmed. Null when absent.
- A feed that fails (network error, HTTP ≥ 400, or unparseable XML) is logged at WARNING. The other feed still counts. The poll is `ok` if at least one feed parsed.

## 5. Matching
- Use the existing `scraper.chip_key` machinery, as discovery does, against the tracked watchlist of the feed's category:
  1. Skip the item when `is_excluded` / `is_excluded_title` matches (bundles, prebuilt PCs, laptops, and so on).
  2. Key = `chip_key(title)`, falling back to `chip_key(slug with "-" -> " ")` for each product tag.
  3. Resolve the key with `Matcher`, which handles VRAM. When a chip is tracked in several VRAM variants, the title must name the VRAM (`parse_vram`), otherwise the item is **unmatched** (`product_id` null).
- An item that resolves to no tracked product is stored unmatched.

## 6. Storage
```sql
CREATE TABLE ozb_deals (
    node_id        INTEGER PRIMARY KEY,
    category       TEXT    NOT NULL,          -- 'gpu' | 'cpu' (the feed it came from)
    title          TEXT    NOT NULL,
    url            TEXT    NOT NULL,          -- the node page, never /goto/
    price_aud      REAL,                      -- parsed from the title; NULL if none
    retailer       TEXT,                      -- after " @ " in the title; NULL if none
    votes_pos      INTEGER NOT NULL DEFAULT 0,
    votes_neg      INTEGER NOT NULL DEFAULT 0,
    comment_count  INTEGER NOT NULL DEFAULT 0,
    posted_at      TEXT,
    starts_at      TEXT,
    expires_at     TEXT,
    expired        INTEGER NOT NULL DEFAULT 0,
    product_id     INTEGER REFERENCES products(id),  -- NULL = unmatched
    first_seen_at  TEXT    NOT NULL,
    last_seen_at   TEXT    NOT NULL,
    alerted_at     TEXT
);
CREATE INDEX idx_ozb_deals_product ON ozb_deals(product_id, expired);

CREATE TABLE ozb_polls (
    polled_at  TEXT    PRIMARY KEY,
    ok         INTEGER NOT NULL,
    items      INTEGER NOT NULL DEFAULT 0,
    error      TEXT
);
```
- **Upsert** each poll on `node_id`. Refresh votes, comments, expiry, expired and `last_seen_at`. Keep `first_seen_at`, `alerted_at` and a non-null `product_id`. A deal that drops off the feed keeps its last state until retention removes it.
- **Retention:** rows with `last_seen_at` older than 180 days are deleted at the end of a poll. They are a report, not history.
- **Logging:** every poll writes one `ozb_polls` row. Rows older than 30 days are deleted.

## 7. Alerts
A deal is sent once, to the digest webhook (`DISCORD_WEBHOOK_URL`) via `notify_discord.send_embed`, when **all** of these hold:
- `product_id` is not null, `alerted_at` is null, and `expired = 0`;
- `starts_at` is null or not in the future;
- `price_aud` is not null;
- `votes_pos − votes_neg ≥ 0`;
- `price_aud` < the product's cheapest **in-stock** price on its latest snapshot date across our retailers. A product with no in-stock price today alerts if the other rules hold.

Rules for sending:
- `alerted_at` is set only after the webhook call succeeds, so a failed send is retried on the next poll.
- With no webhook configured, nothing is sent and `alerted_at` stays null.
- At most 5 deals are sent per poll, cheapest-relative first. The rest wait for the next poll.

The embed:
- **Title:** "OzBargain: <product name> $<price> at <retailer>".
- **Body:** "Our best today: $<price> at <retailer>" (or "not in stock at our retailers"), "+<pos>/−<neg> votes", and links to the deal node and the Trackaroo product page (`TRACKAROO_PUBLIC_BASE_URL`, as the digest uses).
- No emojis.

## 8. Scheduling
- `deploy/entrypoint-single.sh` gains `ozb_loop`, following the `staleness_loop` pattern. It wakes every hour. When the hour is in `OZB_POLL_HOURS` (default `07,09,11,13,15,17,19,21,23`) and that hour has not been polled today, it runs `python ozbargain.py`.
- `OZB_ENABLED=0` disables the loop. It never starts under `SKIP_PIPELINE=1`.
- `python ozbargain.py` runs one poll by hand. `--dry-run` parses and matches, then prints, with no writes and no Discord.

## 9. Health
`check_ozbargain` runs with the daily health checks. It is WARNING-only:
- it warns when there has been no `ok` poll in the last 24 hours;
- it is silent when the table is missing (first deploy) or `OZB_ENABLED=0`;
- it never returns ERROR, so it can never suppress the Discord digest.

## 10. UI
- **Product page:** an "OzBargain deals" panel, shown only when the product has matched deals.
  - It lists live deals, newest first, at most 5.
  - Each row shows the price ("price in post" when null), the retailer, the votes ("+42 / −3"), the age ("posted 3h ago") and a "View deal" link to the node page (`target=_blank rel=noopener`), with a Lucide `ArrowUpRight` icon.
  - A "Show expired (N)" toggle reveals expired deals from the last 30 days, muted and labelled "Expired".
  - Deals cheaper than today's best in-stock price get the existing success tone and a "Below our best" label.
- **/deals:** an "OzBargain" chip on items with a live matched deal. It links to the cheapest live deal, uses a Lucide `Tag` icon and shows its price.
- No emojis. Lucide icons are `aria-hidden`, existing tokens only, and axe and contrast pass in both themes.

## 11. Testing
- **pytest:**
  - parsing of a saved feed fixture (`unit_testing/fixtures/ozbargain_video_card_feed.xml`): node id, price formats, retailer, votes, expiry, expired title-msg, product tags, and an item with no price;
  - matching: exact, the slug fallback, VRAM-ambiguous gives unmatched, and bundle and prebuilt exclusion;
  - upsert idempotence and field refresh;
  - retention;
  - the alert rule at each edge: price equal to best, net-negative votes, expired, future start, no price, already alerted, failed send, no webhook, and the cap of 5;
  - a budget test pinning 2 GETs per poll;
  - `check_ozbargain` WARNING-only;
  - the entrypoint loop present, honouring `OZB_ENABLED` and `SKIP_PIPELINE`, and keeping LF line endings (`test_shell_scripts`);
  - an autouse conftest guard for `ozbargain.DB_PATH`.
- **vitest:** the loader and query (live vs expired, cap, ordering, below-best flag), and the chip data on deals.
- **Playwright:** seeded deals (live, expired, below best) on a fixture product. Covers the panel, the toggle and the /deals chip, with axe in both themes.

## 12. Deploy
- Merge, then run `deploy/redeploy.sh` outside 04:00–09:59. The migration adds both tables. The first poll runs at the next poll hour.
- Run `docker compose exec trackaroo python ozbargain.py --dry-run` once to see matches without alerting.
- Add a CHANGELOG line under Unreleased.
