# RAM Tracking — Scope & Implementation Plan

## Overview

Add desktop RAM (DDR4 and DDR5) tracking to Trackaroo using the same scrape → JSON → DB pipeline as CPU/GPU.

## Key Differences from CPU/GPU

RAM products have more identifying attributes:
- **Type:** DDR4 or DDR5
- **Capacity:** 16GB, 32GB, 64GB (per kit)
- **Speed:** 3200MHz, 3600MHz, 6000MHz, 6400MHz, etc.
- **Timings:** CL16, CL18, CL19, CL20, etc. (CAS Latency)
- **Brand:** G.Skill, Corsair, Kingston, TeamGroup, etc.

**Same product across retailers** = same type + capacity + speed + timings. Brand may vary (e.g., G.Skill vs Corsair at same specs).

## Proposed Schema Changes

### Option A: Extend existing `products` table (recommended)

```sql
-- Add new columns to products table
ALTER TABLE products ADD COLUMN ram_type TEXT CHECK (ram_type IN ('ddr4', 'ddr5', NULL));
ALTER TABLE products ADD COLUMN ram_capacity_gb INTEGER CHECK (ram_capacity_gb IS NULL OR ram_capacity_gb > 0);
ALTER TABLE products ADD COLUMN ram_speed_mhz INTEGER CHECK (ram_speed_mhz IS NULL OR ram_speed_mhz > 0);
ALTER TABLE products ADD COLUMN ram_timings TEXT CHECK (ram_timings IS NULL OR ram_timings GLOB '[0-9]*');

-- Update category constraint to allow 'ram'
-- (requires table rebuild or new column)
```

**Pros:** Minimal changes, reuses existing pipeline
**Cons:** `category` CHECK constraint needs updating; many nullable columns

### Option B: New `ram_products` table

Separate table with RAM-specific fields, linked to same `retailer_listings` and `price_snapshots`.

**Pros:** Clean separation, no nullable bloat
**Cons:** More complex queries for cross-category views

**Recommendation:** Option A — simpler and the existing pipeline handles it cleanly.

## Watchlist Structure

Similar to `db/watchlist.csv` but with RAM-specific fields:

```csv
# db/ram_watchlist.csv
category,brand,model,ram_type,ram_capacity_gb,ram_speed_mhz,ram_timings,gen_tier,search_aliases
ram,G.Skill,Trident Z5 RGB 32GB 6000MHz CL30,ddr5,32,6000,30,current,"trident z5 32gb 6000 cl30|f5-6000j3039g32gztz5rx"
ram,Corsair,Vengeance 32GB 5600MHz CL36,ddr5,32,5600,36,current,"vengeance 32gb 5600 cl36|cmh32gx5m5c36u1"
```

## Scope Rules for RAM

### DDR5 (Current)
- **Sweet spot:** 6000MHz CL30 (AMD EXPO) / 6000MHz CL30 (Intel XMP)
- **Track:** 32GB kits at 5600-6400MHz, 64GB kits at 5600-6000MHz
- **Exclude:** 128GB+ kits (enthusiast/workstation), ECC, registered DIMMs

### DDR4 (Legacy but still relevant)
- **Sweet spot:** 3600MHz CL18 (AMD Ryzen 5000/7000 compatible)
- **Track:** 32GB kits at 3200-3600MHz, 16GB kits at 3200-3600MHz
- **Exclude:** 2400-2933MHz (too slow), 3800MHz+ (niche)

### Brand priorities
Focus on brands commonly stocked by Scorptec/PCCG:
- G.Skill (Trident Z, Flare X5)
- Corsair (Vengeance, Dominator)
- Kingston (Fury Beast)
- TeamGroup (T-Force Delta)
- ADATA (XPG Lancer)

## Implementation Steps

### Step 1: Schema migration (~30 min)
1. Create migration script to add RAM columns to `products` table
2. Update `category` CHECK constraint to include `'ram'`
3. Add indexes for RAM-specific queries (e.g., `ram_type`, `ram_speed_mhz`)
4. Add tests for new schema

### Step 2: Watchlist creation (~1 hour)
1. Research current RAM prices at Scorptec/PCCG
2. Create `db/ram_watchlist.csv` with ~20-30 kits (mix of DDR4/DDR5)
3. Verify against scope rules

### Step 3: Scraper updates (~1-2 hours)
1. Update `fetch_test.py` to handle RAM category pages
2. Update `scraper/pccg.py` to handle RAM products
3. Add RAM-specific fields to JSON output (`ram_type`, `ram_capacity_gb`, `ram_speed_mhz`, `ram_timings`)
4. Test with dry runs

### Step 4: Ingestion updates (~30 min)
1. Update `ingest.py` to handle RAM products
2. Add RAM fields to product creation logic
3. Add tests for RAM ingestion

### Step 5: Daily runner updates (~15 min)
1. Update `run_daily.py` to include RAM scrapes
2. Test full pipeline with RAM data

### Step 6: Frontend considerations (Phase 3)
1. Add RAM filters (type, capacity, speed)
2. Show RAM-specific columns in product table
3. Consider "price per GB" calculation for comparison

## Estimated Effort

| Step | Time | Complexity |
|---|---|---|
| Schema migration | 30 min | Low |
| Watchlist creation | 1 hour | Low (research-heavy) |
| Scraper updates | 1-2 hours | Medium (new category pages) |
| Ingestion updates | 30 min | Low |
| Daily runner updates | 15 min | Low |
| Tests | 1 hour | Medium |
| **Total** | **~4-5 hours** | |

## Risks & Considerations

- **RAM naming varies more than CPU/GPU** — same specs may have different model names across brands
- **Timings may not always be in product title** — may need to parse from product description
- **Kit vs single DIMM** — need to be consistent (track kits, not individual sticks)
- **XMP vs EXPO profiles** — same physical kit may have different profiles for AMD/Intel
- **Scorptec/PCCG may have different RAM category pages** — need to verify

## Decisions (locked)

### 1. Separate JSON files for DDR4 and DDR5
**Decision:** Yes — follow the same pattern as CPU/GPU. Separate files per retailer per type.

```
data/ram_ddr4_scorptec_11_August_2026.json
data/ram_ddr5_scorptec_11_August_2026.json
data/ram_ddr4_pccg_11_August_2026.json
data/ram_ddr5_pccg_11_August_2026.json
```

This keeps files smaller and makes it easy to run one type without the other.

### 2. Price per GB
**Decision:** No — not tracking this as a first-class field. Could be added later as a derived calculation in the frontend (e.g., `price_aud / ram_capacity_gb`) if useful.

### 3. XMP vs EXPO profiles
**Decision:** Track both if available during scraping. XMP (Intel) and EXPO (AMD) are functionally equivalent — they're just branded SPD profiles for the same physical kit. If a retailer lists the same kit with both profiles, treat it as one product. The `search_aliases` column in the watchlist can include both profile names to ensure matching works.

**Example:** A G.Skill Trident Z5 kit sold as "XMP 6000MHz CL30" on one site and "EXPO 6000MHz CL30" on another → same product, matched by speed + timings + capacity.

## Open Questions

1. How do we handle kits with different timing profiles (e.g., CL30 vs CL32 at same speed)? → Treat as separate products since they're different SKUs with different prices.
2. Should we track single DIMMs or only kits? → **Kits only** for now (16GB = 2x8GB, 32GB = 2x16GB). Single DIMMs add complexity without much personal-use value.
