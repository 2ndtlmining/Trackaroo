
-- AU CPU/GPU Price Tracker — SQLite schema
-- Implements the data model in SPEC.md §7 and the retention policy in §7a.
-- Reminder: rows in this schema are never deleted. Products/listings that
-- stop being tracked are marked via `tracked` / `status`, not removed.

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────
-- products: canonical, cross-retailer product identity
-- ─────────────────────────────────────────────────────────────
CREATE TABLE products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT    NOT NULL CHECK (category IN ('cpu', 'gpu')),
    brand               TEXT    NOT NULL,               -- e.g. 'AMD', 'Intel', 'NVIDIA'
    model               TEXT    NOT NULL,               -- e.g. 'Ryzen 7 9800X3D', 'RTX 5070 Ti'
    variant             TEXT,                           -- e.g. AIB partner/edition, if tracked at that granularity
    vram_gb             INTEGER,                        -- GPU only
    cores               INTEGER,                        -- CPU only
    generation_tier     TEXT    CHECK (generation_tier IN ('current', 'current-1', 'current-2')),
                                                          -- per SCOPE_RULES.md; kept even after a product rolls
                                                          -- out of scope, as a historical record of where it sat
    tracked             INTEGER NOT NULL DEFAULT 1,      -- 0/1. false once rolled out of scope per SCOPE_RULES.md
    last_snapshot_at    TEXT,                            -- ISO8601 UTC. auto-maintained by trigger below
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_products_category_tracked ON products (category, tracked);

-- ─────────────────────────────────────────────────────────────
-- retailer_listings: a specific retailer's page for a product variant
-- Multiple listings can exist per product (e.g., GIGABYTE, ASUS, Zotac 5090)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE retailer_listings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id          INTEGER NOT NULL REFERENCES products(id),
    retailer            TEXT    NOT NULL CHECK (retailer IN ('scorptec', 'pccg', 'mwave')),
    variant_name        TEXT,                            -- specific variant/brand model, e.g. 'GIGABYTE AORUS RTX 5090 AI Box'
    retailer_sku        TEXT,                            -- retailer's own SKU/product code, if available
    listing_url         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'delisted', 'stale')),
                                 -- active  = currently tracked and scraped
                                 -- delisted = retailer removed the listing
                                 -- stale    = we stopped scraping it (e.g. product rolled out of scope)
    first_seen_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at        TEXT,                            -- last time the listing was confirmed present on-site
    last_snapshot_at    TEXT,                            -- ISO8601 UTC. auto-maintained by trigger below
    UNIQUE (retailer, listing_url)
);

CREATE INDEX idx_retailer_listings_product ON retailer_listings (product_id);
CREATE INDEX idx_retailer_listings_status ON retailer_listings (retailer, status);

-- ─────────────────────────────────────────────────────────────
-- price_snapshots: one row per listing per scrape. Append-only —
-- never updated or deleted once written.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE price_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer_listing_id     INTEGER NOT NULL REFERENCES retailer_listings(id),
    snapshot_date           TEXT    NOT NULL,            -- 'YYYY-MM-DD', one intended snapshot per listing per day
    price_aud               REAL    NOT NULL,
    stock_status             TEXT    NOT NULL DEFAULT 'unknown'
                                 CHECK (stock_status IN ('in_stock', 'out_of_stock', 'preorder', 'unknown')),
    scraped_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (retailer_listing_id, snapshot_date)
);

CREATE INDEX idx_snapshots_listing_date ON price_snapshots (retailer_listing_id, snapshot_date);
CREATE INDEX idx_snapshots_date ON price_snapshots (snapshot_date);

-- ─────────────────────────────────────────────────────────────
-- Triggers: keep last_snapshot_at in sync automatically whenever a
-- new snapshot is written, so no application code has to remember
-- to do this — it's enforced at the database level.
-- ─────────────────────────────────────────────────────────────
CREATE TRIGGER trg_update_listing_last_snapshot
AFTER INSERT ON price_snapshots
BEGIN
    UPDATE retailer_listings
    SET last_snapshot_at = NEW.scraped_at,
        last_seen_at = NEW.scraped_at
    WHERE id = NEW.retailer_listing_id;

    UPDATE products
    SET last_snapshot_at = NEW.scraped_at
    WHERE id = (
        SELECT product_id FROM retailer_listings WHERE id = NEW.retailer_listing_id
    )
    AND (last_snapshot_at IS NULL OR last_snapshot_at < NEW.scraped_at);
END;