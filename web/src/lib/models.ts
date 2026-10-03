// Client-safe DTO types shared by server repos and Svelte components (#30).
// Types only: no runtime code, and nothing here may import from $lib/server.
import type {
	Category,
	GenerationTier,
	ListingStatus,
	Retailer,
	StockStatus
} from './types';

export interface ProductRow {
	id: number;
	category: Category;
	brand: string;
	model: string;
	variant: string | null;
	vram_gb: number | null;
	cores: number | null;
	generation_tier: GenerationTier | null;
	tracked: number;
	last_snapshot_at: string | null;
	created_at: string;
}

export interface ListingRow {
	id: number;
	product_id: number;
	retailer: Retailer;
	variant_name: string | null;
	retailer_sku: string | null;
	listing_url: string;
	status: ListingStatus;
	first_seen_at: string;
	last_seen_at: string | null;
	last_snapshot_at: string | null;
}

export interface SnapshotRow {
	id: number;
	retailer_listing_id: number;
	snapshot_date: string;
	price_aud: number;
	stock_status: StockStatus;
	scraped_at: string;
}

export interface SpecRow {
	spec_id: number;
	product_id: number;
	source: string;
	source_record_key: string;
	category: Category;
	architecture: string | null;
	generation: string | null;
	launch_date: string | null;
	launch_msrp_usd: number | null;
	vram_gb: number | null;
	memory_bus_width_bit: number | null;
	memory_type: string | null;
	tdp_watts: number | null;
	core_count: number | null;
	thread_count: number | null;
	base_clock_mhz: number | null;
	boost_clock_mhz: number | null;
	socket: string | null;
	cache_l3_mb: number | null;
	gpu_die: string | null;
	bus_interface: string | null;
	memory_bandwidth_gbps: number | null;
	memory_clock_mhz: number | null;
	process_nm: number | null;
	foundry: string | null;
	codename: string | null;
	l1_cache_kb: number | null;
	l2_cache_mb: number | null;
	memory_speed_mhz: number | null;
	memory_channels: number | null;
	memory_types: string | null;
	integrated_graphics: string | null;
	raw_json: string;
	last_synced_at: string;
}

export interface SparklinePoint {
	listingId: number;
	date: string;
	price: number;
}

// A dated price point; the shape Sparkline.svelte draws.
export interface PricePoint {
	date: string;
	price: number;
}

export interface LatestListing {
	listingId: number;
	productId: number;
	category: Category;
	brand: string;
	model: string;
	productVariant: string | null;
	generationTier: GenerationTier | null;
	retailer: Retailer;
	variantName: string | null;
	listingUrl: string;
	status: ListingStatus;
	lastSnapshotAt: string | null;
	latestDate: string;
	latestPrice: number;
	latestStock: StockStatus;
	latestScrapedAt: string;
	windowStartDate: string | null;
	windowStartPrice: number | null;
	pointsInWindow: number;
	sparkline?: SparklinePoint[];
}

export interface ProductGroup {
	productId: number;
	category: Category;
	brand: string;
	model: string;
	productVariant: string | null;
	generationTier: GenerationTier | null;
	listings: LatestListing[];
	cheapestInStockPrice: number | null;
	cheapestInStockRetailer: Retailer | null;
	inStockCount: number;
	// Average of the per-day cheapest in-stock price over the trailing 30 days
	// (null when no in-stock history in the window).
	avg30?: number | null;
	// Days that actually contributed to avg30. The window is 30 days but a
	// young dataset has fewer, and the UI labels the real number.
	avg30Points?: number;
}

export interface Mover {
	listingId: number;
	productId: number;
	category: Category;
	brand: string;
	model: string;
	retailer: Retailer;
	variantName: string | null;
	listingUrl: string;
	oldPrice: number | null;
	newPrice: number;
	change: number | null;
	pctChange: number | null;
	pointsInWindow: number;
	historyPoints: number;
	notEnoughHistory: boolean;
	windowStart: string | null;
	windowEnd: string;
	sparkline?: SparklinePoint[];
}

export interface Series {
	listing: ListingRow;
	points: SnapshotRow[];
}

export interface PriceBandPoint {
	date: string;
	low: number | null; // MIN price among in-stock snapshots that day
	high: number | null; // MAX price among in-stock snapshots that day
	cheapestInStock: number | null; // cheapest in-stock price at the latest snapshot (single point)
}

export interface ProductHistory {
	product: ProductRow;
	series: Series[];
	specs: SpecRow | null;
	band: PriceBandPoint[];
	// Trailing-30-day stats for the detail page's "30d avg" chip.
	stats: ProductStats;
	// Latest snapshot_date per retailer, across all products -- lets the display
	// layer tell "this listing's own retailer hasn't been scraped in days"
	// (not stale) apart from "everyone else moved on and this one didn't" (#4).
	retailerLatest: Record<string, string>;
}

export interface TrackedProduct {
	productId: number;
	category: Category;
	brand: string;
	model: string;
	productVariant: string | null;
	generationTier: GenerationTier | null;
	vramGb: number | null;
	cores: number | null;
}

export interface ProductIndexEntry {
	id: number;
	category: Category;
	brand: string;
	model: string;
	productVariant: string | null;
	// For the display-name rule (displayName.ts).
	vramGb: number | null;
	// Total price snapshots across the product's listings — lets the palette
	// show which products actually have price history yet.
	snapshotCount: number;
}

export interface HeaderStats {
	latestSnapshotDate: string | null;
	earliestSnapshotDate: string | null;
	snapshotCount: number;
	snapshotDays: number;
	dbSizeBytes: number;
}

export interface RetailerFreshness {
	retailer: Retailer;
	latestSnapshotDate: string | null;
	// Latest scrape_runs row (R3): local wall-clock 'YYYY-MM-DDTHH:MM:SS', its
	// status, and the products it matched. Optional so callers building rows by
	// hand (tests, older data) need not supply them.
	lastRunAt?: string | null;
	lastRunStatus?: string | null;
	lastRunMatched?: number | null;
}

// Average of the per-day cheapest in-stock price over the trailing window
// (the same series the sparklines draw), plus the number of days that series
// has — the point count gates the "30d avg" chip and the deal badge so a
// product with 1-2 days of history is never shown a misleading average.
export interface ProductStats {
	avg30: number | null;
	avg30Points: number;
}

export interface CheapestListing {
	productId: number;
	model: string;
	brand: string;
	variantName: string | null;
	retailer: Retailer;
	price: number;
	snapshotDate: string;
	ninetyDayLow: number | null;
	ninetyDayHigh: number | null;
	// Average of the per-day cheapest in-stock price over the trailing 30
	// days (null when no in-stock history in the window) + day count.
	avg30: number | null;
	avg30Points: number;
}

export interface DealCandidate {
	productId: number;
	category: Category;
	model: string;
	brand: string;
	listingId: number;
	variantName: string | null;
	retailer: Retailer;
	listingUrl: string;
	price: number;
	snapshotDate: string;
	allTimeLow: number | null;
	avg30: number | null;
	avg30Points: number;
	// Highest daily-cheapest in-stock price within the avg30 window -- an
	// earned all-time low needs the price to have actually come DOWN from
	// somewhere, not just sat flat at the low (#6).
	windowHigh: number | null;
	// The product's first in-stock snapshot date across all history, for
	// labelling how far back "all-time" actually reaches (#6).
	historyStart: string | null;
	// US launch MSRP in USD (specs.launch_msrp_usd), for the vs-MSRP cue.
	msrpUsd: number | null;
}

export interface ProductMove {
	productId: number;
	category: Category;
	brand: string;
	model: string;
	oldPrice: number;
	newPrice: number;
	change: number;
	pctChange: number;
	fromDate: string;
	toDate: string;
	// Today's cheapest in-stock listing: where the new price actually is.
	retailer: Retailer;
	variantName: string | null;
}

export interface ComparePrice {
	retailer: Retailer;
	// Best in-stock price on the product's latest snapshot day per listing
	// (null if nothing in stock).
	price: number | null;
}

export interface CompareEntry {
	product: ProductRow;
	spec: SpecRow | null;
	// One entry per retailer that had any in-stock snapshot for the product.
	// Uses each listing's own latest snapshot (LATEST_CTE), not a single
	// global date — a retailer that skipped a day (e.g. PCCG cooldown) still
	// reports its most recent real price instead of vanishing.
	prices: ComparePrice[];
	// Cheapest in-stock price across all retailers' latest snapshots.
	cheapestInStock: { price: number; retailer: Retailer } | null;
}

// Alerts, FX, OzBargain and value DTOs (#61: split to keep this file under the cap).
export type * from './modelsFeatures';
