# Performance index sources (`db/perf_index.json`)

The price-to-performance view (#33) uses a hand-curated index. Each metric comes
from **one** published chart, so every value in a metric shares one baseline.
Values are the published relative percentages, unchanged. A tracked product that
the chart does not list goes to `not_in_source[metric]`. It is never estimated,
interpolated, averaged across charts or copied from a sibling (a K value is not
reused for the KF, and an 8 GB card never borrows the 16 GB figure).

Transcribed 3-Oct-2026. TechPowerUp publishes its summary charts as PNG images,
so the values were read from the chart images, linked below, and checked again on
2x crops. TechPowerUp's pages returned HTTP 403 to the WebFetch tool. The review
pages and chart images were fetched directly over HTTPS (curl) in the same session.

## Metrics

| Metric | Source | Chart | Published | Baseline (100%) |
|---|---|---|---|---|
| `gpu_raster_1440p` | TechPowerUp, *ASUS GeForce RTX 5090 Matrix Platinum Review - 800 W Powerhouse*, p. 31 "Relative Performance" ([page](https://www.techpowerup.com/review/asus-geforce-rtx-5090-matrix/31.html)) | [relative-performance-2560-1440.png](https://tpucdn.com/review/asus-geforce-rtx-5090-matrix/images/relative-performance-2560-1440.png) | 28-Apr-2026 (UTC) | ASUS RTX 5090 Matrix 32 GB / 800 W |
| `gpu_rt_1440p` | Same review, p. 33 "Ray Tracing" ([page](https://www.techpowerup.com/review/asus-geforce-rtx-5090-matrix/33.html)) | [relative-performance-rt-2560-1440.png](https://tpucdn.com/review/asus-geforce-rtx-5090-matrix/images/relative-performance-rt-2560-1440.png) | 28-Apr-2026 (UTC) | ASUS RTX 5090 Matrix 32 GB / 800 W |
| `cpu_gaming_1080p` | TechPowerUp, *AMD Ryzen 7 7700X3D Review*, p. 24 "Performance Summary" ([page](https://www.techpowerup.com/review/amd-ryzen-7-7700x3d/24.html)) | [relative-performance-games-1920-1080.png](https://tpucdn.com/review/amd-ryzen-7-7700x3d/images/relative-performance-games-1920-1080.png) | 16-Jul-2026 (UTC) | Ryzen 7 7700X3D |

### Why these reviews

- **GPUs.** The brief asked for the 2025–2026 TechPowerUp GPU review whose 1440p
  Relative Performance chart lists the most cards. The 2026 reviews on the
  "GPU 2025.2" test bed (Ryzen 7 9800X3D) were compared by chart size:
  - the RTX 5090 Matrix review (28-Apr-2026) has 44 entries: 40 reference cards
    plus four RTX 5090 Matrix / Lightning Z power configurations;
  - the PNY RTX 5080 Slim, Colorful RTX 5070 Mini, ASRock RX 9070 XT Taichi,
    MSI RTX 5070 Ti Ventus and other 2026 reviews have 41 (the same 40
    reference cards plus the tested card);
  - the newer RX 9070 GRE reviews (2-Jun-2026) have only 35, and drop the RTX 40
    Super cards and the RTX 3050.

  The raster and RT charts come from the same review.
- **CPUs.** The rule is the GPU rule (ruling R3): use the 2025–2026
  TechPowerUp CPU review on an RTX 4090/5090 test bed whose "Relative
  Performance, Games 1920x1080" chart lists the most tracked CPUs (any tier).
  Every 2025–2026 review in TechPowerUp's Processors category was fetched and
  its chart counted:

  | Review | Published | Chart entries | Tracked matches (all tiers) | Required matches (current + current-1, of 38) |
  |---|---|---|---|---|
  | AMD Ryzen 7 7700X3D | 16-Jul-2026 | 20 | **16** | **15** |
  | AMD Ryzen 9 9950X3D2 Dual Edition | 9-Jun-2026 | 17 | 12 | 12 |
  | Intel Core Ultra 7 270K Plus | 23-Mar-2026 | 17 | 12 | 12 |
  | Intel Core Ultra 5 250K Plus | 23-Mar-2026 | 15 | 12 | 12 |
  | AMD Ryzen 7 9850X3D | 28-Jan-2026 | 13 | 11 | 11 |
  | AMD Ryzen 9 9950X3D | 11-Mar-2025 | 8 | 7 | 7 |

  - TechPowerUp has no Ryzen 9 9900X3D review; `/review/amd-ryzen-9-9900x3d/`
    returns 404, and it is not in the Processors listing.
  - The Arrow Lake refresh is the 270K Plus / 250K Plus pair above. No Zen 6
    review is listed.
  - The Ryzen 7 9800X3D (Nov 2024, 49 entries) and Core Ultra 285K / 265K /
    245K (Oct 2024) reviews predate the 2025–2026 window, so they are not
    eligible.

  The Ryzen 7 7700X3D review wins: test bed RTX 5090 (Zotac Solid), 2x16 GB
  DDR5-6000. Its chart is still small, so CPU coverage is thin; see the gaps
  below.

### Matching notes

- **Product key rule (ruling R5):**
  - For a GPU whose watchlist `model` already ends with its `spec` as a whole
    word, the key is the `model`: `GeForce RTX 5060 Ti 8GB`,
    `Radeon RX 9060 XT 8GB`, `GeForce RTX 3050 6GB`.
  - For any other GPU, the key is `"<model> <spec>"`, e.g.
    `GeForce RTX 5060 Ti 16GB`.
  - For a CPU, the key is the `model`.
  - `product_key()` in `unit_testing/test_perf_index.py` implements the rule.
- The chart labels give the VRAM, e.g. "RTX 5060 Ti 8 GB". Each GPU was matched
  on model **and** VRAM:
  - RTX 5060 Ti 16 GB and 8 GB are separate rows (raster 35 / 35, RT 35 / 25);
  - RX 9060 XT 16 GB and 8 GB are separate rows;
  - for the RTX 4060 Ti, the watchlist tracks only the 8 GB card. The chart's
    "RTX 4060 Ti 8 GB" row was used and its 16 GB row ignored;
  - "RTX 3050 8 GB" maps to `GeForce RTX 3050 8GB`. The chart has no 6 GB RTX
    3050.
- Rows that are not tracked products were ignored: the RTX 5090 Matrix and
  Lightning Z configurations, RTX 5050, RTX 2060, RX 7600 XT and RTX 4060 Ti
  16 GB (GPU); Ryzen 7 9850X3D, Ryzen 7 7700X3D, Core Ultra 7 270K Plus and
  Core Ultra 5 250K Plus (CPU).
- **RX 9070 GRE.** No TechPowerUp chart from this test bed lists a reference
  RX 9070 GRE. The 9070 GRE reviews show only the partner card under test
  (e.g. "Sapphire RX 9070 GRE Pulse 12 GB") and its own baseline, so it is
  `not_in_source`.
- **K and KF CPUs.** These are separate products. The chart lists only the K
  parts, so i7-14700KF, i9-14900KF, Ultra 7 265KF and Ultra 5 245KF are
  `not_in_source`.

## Coverage

| Metric | current | current-1 | current-2 |
|---|---|---|---|
| `gpu_raster_1440p` | 12/14 | 16/18 | 8/18 |
| `gpu_rt_1440p` | 12/14 | 16/18 | 8/18 |
| `cpu_gaming_1080p` | 8/15 | 7/24 | 1/17 |

## Not in source

**`gpu_raster_1440p` and `gpu_rt_1440p`** (same list for both)
- current: Radeon RX 9070 GRE 12GB, Arc B570 10GB
- current-1: Arc A380 6GB, Arc A750 8GB
- current-2: GeForce RTX 3050 6GB, GeForce RTX 3070 Ti 8GB,
  GeForce RTX 3080 Ti 12GB, GeForce RTX 3090 24GB, Radeon RX 6600 8GB,
  Radeon RX 6650 XT 8GB, Radeon RX 6700 XT 12GB, Radeon RX 6750 XT 12GB,
  Radeon RX 6800 16GB, Radeon RX 6950 XT 16GB

**`cpu_gaming_1080p`**
- current: Ryzen 9 9900, Ryzen 9 9900X, Ryzen 9 9900X3D, Ryzen 9 9950X3D2,
  Core Ultra 5 245, Core Ultra 5 245KF, Core Ultra 7 265KF
- current-1: Ryzen 5 7600, Ryzen 5 7600X3D, Ryzen 5 8600G, Ryzen 9 7900,
  Ryzen 9 7900X, Ryzen 9 7900X3D, Ryzen 9 7950X3D, Core i5-14400,
  Core i5-14400F, Core i5-14500, Core i5-14600K, Core i5-14600KF,
  Core i7-14700KF, Core i9-14900, Core i9-14900KF, Core i9-14900F,
  Core i9-14900KS
- current-2: every tracked CPU except Ryzen 7 5800X3D (16 products)

## Updating

1. Pick one newer chart per metric and record it in the table above.
2. Re-transcribe **every** value for that metric from the new chart. Never mix
   old and new values within a metric.
3. Rebuild `not_in_source` from the new chart. GPU raster and CPU gaming are
   required for current and current-1 products. Ray tracing is required only
   where the RT chart lists the card; otherwise the card goes to
   `not_in_source.gpu_rt_1440p`.
4. Update the pinned VRAM-variant values in the tests
   (`unit_testing/test_perf_index.py`, `web/test/value.test.ts`,
   `web/test/compareRows.test.ts`).
5. Run `python -m pytest -q unit_testing/test_perf_index.py`.
