# Product Scope Rules

This file defines which CPUs and GPUs are in scope for tracking. It is the source of truth for the watchlist — consult it whenever adding, questioning, or excluding a product.

## Core rule: 2-generation limit

**Track the current generation plus the two generations before it. Do not track anything older than that (current minus 3 or beyond).**

In other words: `current`, `current - 1`, `current - 2` are tracked. `current - 3` and older are excluded.

This rule applies independently per product line (AMD CPU, Intel CPU, NVIDIA GPU, AMD GPU), since each moves on its own release cadence. It is **not** a fixed calendar cutoff — it moves forward as new generations launch, and this file should be revisited/updated when that happens (see §6).

## 1. AMD Ryzen desktop CPUs

| Tier | Series | Architecture | Socket |
|---|---|---|---|
| Current | Ryzen 9000 | Zen 5 | AM5 |
| −1 | Ryzen 7000 (incl. 8000G APUs — see note) | Zen 4 | AM5 |
| −2 | Ryzen 5000 | Zen 3 | AM4 |
| **Excluded (−3)** | Ryzen 3000 and older (e.g. 3900X) | Zen 2 and older | AM4 |

**Note on naming:** the Ryzen 8000G series is a desktop APU line built on Zen 4 silicon, not a new architecture — despite the "8000" number, it sits in the same generation tier as the 7000 series (−1), not its own tier.

## 2. Intel desktop CPUs

| Tier | Series | Codename | Socket |
|---|---|---|---|
| Current | Core Ultra 200 series | Arrow Lake | LGA1851 |
| −1 | Core 14th Gen | Raptor Lake Refresh | LGA1700 |
| −2 | Core 13th Gen | Raptor Lake | LGA1700 |
| **Excluded (−3)** | Core 12th Gen and older | Alder Lake and older | LGA1700 and older |

**Note:** Intel's Core Ultra 300 series ("Panther Lake") launched in Jan 2026 but is a mobile/laptop-first platform — no desktop socket parts as of this writing. Desktop stays on Core Ultra 200 as current until a desktop Panther Lake or Nova Lake part ships; revisit this file when that happens.

## 3. NVIDIA GeForce GPUs

| Tier | Series | Architecture |
|---|---|---|
| Current | RTX 50 series | Blackwell |
| −1 | RTX 40 series | Ada Lovelace |
| −2 | RTX 30 series | Ampere |
| **Excluded (−3)** | RTX 20 series and older | Turing and older |

## 4. AMD Radeon GPUs

| Tier | Series | Architecture |
|---|---|---|
| Current | RX 9000 series | RDNA 4 |
| −1 | RX 7000 series | RDNA 3 |
| −2 | RX 6000 series | RDNA 2 |
| **Excluded (−3)** | RX 5000 series and older | RDNA 1 and older |

## 5. Intel Arc GPUs

Intel's discrete GPU line is younger and has had far fewer generations than AMD/NVIDIA, so the strict 2-gen rule isn't meaningful yet. **Track all current Arc desktop GPUs (Alchemist A-series and Battlemage B-series) without an exclusion tier.** Revisit this exception once Arc has 3+ generations on the market.

## 6. Maintenance of this file

- When a new generation launches for any product line (new Ryzen/Core/GeForce/Radeon series), update the relevant table: promote the new series to "Current," shift the others down one tier, and drop the oldest tier from tracking.
- Dropping a generation from scope means: stop taking new snapshots for those products going forward. Existing historical price data for dropped products should be retained, not deleted, in case it's useful later — just excluded from the active watchlist / "biggest movers" views.
- Workstation/server CPUs (Threadripper, Xeon, EPYC) and professional GPUs (RTX PRO/Ada, Radeon Pro) remain **out of scope entirely**, per §3 of the main spec — this file only governs the consumer desktop CPU/GPU lines listed above.
