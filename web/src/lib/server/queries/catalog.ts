import type { DB } from '../db';
import type { Category, GenerationTier, ListingFilters, ListingStatus, Retailer, StockStatus } from '../../types';
import {
	LATEST_CTE,
	dailyCheapestInStock,
	notBundle,
	pointsInWindowSubquery,
	windowStartPriceSubquery,
	windowStartSubquery
} from './sql';
import type {
	LatestListing,
	ProductGroup,
	ProductIndexEntry,
	SparklinePoint,
	TrackedProduct
} from '../../models';

export const DEFAULT_WINDOW_DAYS = 7;

// Groups per-listing rows into one entry per product (for the Products card
// grid), keeping the row order the SQL produced (category, model).
export function groupListingsByProduct(listings: LatestListing[]): ProductGroup[] {
	const byProduct = new Map<number, ProductGroup>();
	for (const row of listings) {
		let group = byProduct.get(row.productId);
		if (!group) {
			group = {
				productId: row.productId,
				category: row.category,
				brand: row.brand,
				model: row.model,
				productVariant: row.productVariant,
				generationTier: row.generationTier,
				listings: [],
				cheapestInStockPrice: null,
				cheapestInStockRetailer: null,
				inStockCount: 0
			};
			byProduct.set(row.productId, group);
		}
		group.listings.push(row);
		if (row.latestStock === 'in_stock') {
			group.inStockCount += 1;
			if (group.cheapestInStockPrice === null || row.latestPrice < group.cheapestInStockPrice) {
				group.cheapestInStockPrice = row.latestPrice;
				group.cheapestInStockRetailer = row.retailer;
			}
		}
	}

	return [...byProduct.values()];
}

// Canonical display names for AIB/GPU partner brands, keyed by the lowercase
// first token of the retailer variant name (e.g. "Gigabyte GeForce RTX 5060
// Windforce OC GDDR7 8GB" -> "Gigabyte"). Used to group the per-product
// listings panel by brand. Unknown prefixes fall back to the product brand.
export { AIB_BRAND_ALIASES, deriveListingBrand } from '$lib/branding';

interface LatestRow {
	listing_id: number;
	product_id: number;
	category: Category;
	brand: string;
	model: string;
	product_variant: string | null;
	generation_tier: GenerationTier | null;
	retailer: Retailer;
	variant_name: string | null;
	listing_url: string;
	status: ListingStatus;
	last_snapshot_at: string | null;
	latest_date: string;
	latest_price: number;
	latest_stock: StockStatus;
	latest_scraped_at: string;
	window_start_date: string | null;
	window_start_price: number | null;
	points_in_window: number;
}

function filtersToParams(filters: ListingFilters): { clause: string; params: Record<string, string> } {
	const clauses: string[] = [];
	const params: Record<string, string> = {};
	if (filters.category) {
		clauses.push('p.category = @category');
		params.category = filters.category;
	}
	if (filters.inStock) {
		clauses.push("lat.stock_status = 'in_stock'");
	}
	return { clause: clauses.length ? ` AND ${clauses.join(' AND ')}` : '', params };
}

// Every tracked product in a category, whether or not a retailer has ever
// listed it. The index needs these: ~39% of the watchlist has never matched a
// listing, and silently omitting them makes a search for a genuinely tracked
// model answer "no match", which is not the same thing as "not stocked".
export function getTrackedProducts(db: DB, category: Category): TrackedProduct[] {
	const rows = db
		.prepare(
			`SELECT id, category, brand, model, variant, generation_tier, vram_gb, cores
			 FROM products
			 WHERE tracked = 1 AND category = ?
			 ORDER BY model COLLATE NOCASE ASC`
		)
		.all(category) as Array<{
		id: number;
		category: Category;
		brand: string;
		model: string;
		variant: string | null;
		generation_tier: GenerationTier | null;
		vram_gb: number | null;
		cores: number | null;
	}>;
	return rows.map((r) => ({
		productId: r.id,
		category: r.category,
		brand: r.brand,
		model: r.model,
		productVariant: r.variant,
		generationTier: r.generation_tier,
		vramGb: r.vram_gb,
		cores: r.cores
	}));
}

// Release month per product for the catalog's Released column (#23). A
// separate, memoised, per-category read of specs -- specs are still never
// JOINed into a list query (decision log 2026-09-30).
export function getLaunchDates(db: DB, category: Category): Map<number, string> {
	const rows = db
		.prepare(
			`SELECT product_id AS productId, MIN(launch_date) AS launchDate
			 FROM specs
			 WHERE category = ? AND launch_date IS NOT NULL
			 GROUP BY product_id`
		)
		.all(category) as Array<{ productId: number; launchDate: string }>;
	return new Map(rows.map((r) => [r.productId, r.launchDate]));
}

// US launch MSRP per product (USD), for the catalogue's vs-MSRP column and the
// deals list. Same shape as getLaunchDates: one per-category read, never a
// JOIN into a list query. Omit the category for every product.
export function getLaunchMsrps(db: DB, category?: Category): Map<number, number> {
	const rows = db
		.prepare(
			`SELECT product_id AS productId, MIN(launch_msrp_usd) AS msrpUsd
			 FROM specs
			 WHERE launch_msrp_usd IS NOT NULL AND launch_msrp_usd > 0
			   AND (@category IS NULL OR category = @category)
			 GROUP BY product_id`
		)
		.all({ category: category ?? null }) as Array<{ productId: number; msrpUsd: number }>;
	return new Map(rows.map((r) => [r.productId, r.msrpUsd]));
}

// CPU-only spec columns for the catalogue's Socket / Threads columns. Same
// shape as getLaunchDates: one memoisable per-category read, never a JOIN into
// the list query. GPU rows simply have no entry.
export function getCpuSpecs(
	db: DB,
	category: Category
): Map<number, { socket: string | null; threads: number | null }> {
	const rows = db
		.prepare(
			`SELECT product_id AS productId, MIN(socket) AS socket, MIN(thread_count) AS threads
			 FROM specs
			 WHERE category = ? AND (socket IS NOT NULL OR thread_count IS NOT NULL)
			 GROUP BY product_id`
		)
		.all(category) as Array<{ productId: number; socket: string | null; threads: number | null }>;
	return new Map(rows.map((r) => [r.productId, { socket: r.socket, threads: r.threads }]));
}

// Daily cheapest in-stock price per tracked product over the trailing window,
// oldest first, for the catalogue's trend column. One query per category, built
// on dailyCheapestInStock (the window is its bound '?' parameter).
export function getProductSparklines(
	db: DB,
	category: Category,
	days = 30
): Map<number, Array<{ date: string; price: number }>> {
	const rows = db
		.prepare(
			`SELECT d.product_id AS productId, d.snapshot_date AS date, d.price AS price
			 FROM (${dailyCheapestInStock({ form: 'standalone', perProduct: true, window: '?' })}) d
			 JOIN products p ON p.id = d.product_id
			 WHERE p.tracked = 1 AND p.category = ?
			 ORDER BY d.product_id, d.snapshot_date ASC`
		)
		.all(`-${days} days`, category) as Array<{ productId: number; date: string; price: number }>;
	const out = new Map<number, Array<{ date: string; price: number }>>();
	for (const r of rows) {
		const arr = out.get(r.productId) ?? [];
		arr.push({ date: r.date, price: r.price });
		out.set(r.productId, arr);
	}
	// The window is inclusive at both ends, so it can hold days + 1 dates.
	for (const [id, arr] of out) if (arr.length > days) out.set(id, arr.slice(-days));
	return out;
}

export function getProductIndex(db: DB): ProductIndexEntry[] {
	return db
		.prepare(
			`SELECT p.id, p.category, p.brand, p.model, p.variant AS productVariant, p.vram_gb AS vramGb,
			        COUNT(s.id) AS snapshotCount
			 FROM products p
			 LEFT JOIN retailer_listings l ON l.product_id = p.id
			 LEFT JOIN price_snapshots s ON s.retailer_listing_id = l.id
			 WHERE p.tracked = 1
			 GROUP BY p.id
			 ORDER BY p.category, p.model`
		)
		.all() as ProductIndexEntry[];
}

export function getCategoryCounts(db: DB): Map<Category, number> {
	const rows = db
		.prepare('SELECT category, COUNT(*) AS n FROM products WHERE tracked = 1 GROUP BY category')
		.all() as Array<{ category: Category; n: number }>;
	return new Map(rows.map((r) => [r.category, r.n]));
}

/**
 * Tracked products that have at least one active listing -- i.e. the ones you
 * can actually buy right now.
 *
 * `getCategoryCounts` counts the watchlist, which is a statement of intent. On
 * 31-Aug-2026 that was 99 products, 42 of which had no active listing at any
 * retailer, so the dashboard's "47 tracked" GPUs described 23 buyable cards.
 * The gap is not a data fault: those 42 are end-of-life parts (RTX 30/40
 * series, RX 6000/7000, Intel 13th gen) that both retailers have sold out of,
 * verified against their live catalogues. Reporting both numbers is what makes
 * the headline honest, and it self-corrects if anything is restocked.
 */
export function getAvailableCounts(db: DB): Map<Category, number> {
	const rows = db
		.prepare(
			`SELECT p.category AS category, COUNT(DISTINCT p.id) AS n
			 FROM products p
			 JOIN retailer_listings l ON l.product_id = p.id
			 WHERE p.tracked = 1 AND l.status = 'active'
			 GROUP BY p.category`
		)
		.all() as Array<{ category: Category; n: number }>;
	return new Map(rows.map((r) => [r.category, r.n]));
}

export function getLatestListings(
	db: DB,
	filters: Pick<ListingFilters, 'category' | 'inStock'> = {},
	windowDays = DEFAULT_WINDOW_DAYS
): LatestListing[] {
	const { clause, params } = filtersToParams(filters);
	const sql = `
${LATEST_CTE}
		SELECT
			l.id AS listing_id,
			p.id AS product_id,
			p.category,
			p.brand,
			p.model,
			p.variant AS product_variant,
			p.generation_tier,
			l.retailer,
			l.variant_name,
			l.listing_url,
			l.status,
			l.last_snapshot_at,
			lat.snapshot_date AS latest_date,
			lat.price_aud AS latest_price,
			lat.stock_status AS latest_stock,
			lat.scraped_at AS latest_scraped_at,
			${windowStartSubquery('lat.snapshot_date')} AS window_start_date,
			${windowStartPriceSubquery('lat.snapshot_date')} AS window_start_price,
			${pointsInWindowSubquery('lat.snapshot_date')} AS points_in_window
		FROM latest lat
		JOIN retailer_listings l ON l.id = lat.retailer_listing_id
		JOIN products p ON p.id = l.product_id
		WHERE l.status = 'active' AND p.tracked = 1 AND ${notBundle('l')}${clause}
		ORDER BY p.category, p.model, l.retailer, lat.price_aud
	`;

	const rows = db.prepare(sql).all({ window: `-${windowDays} days`, ...params }) as LatestRow[];

	return rows.map((r) => ({
		listingId: r.listing_id,
		productId: r.product_id,
		category: r.category,
		brand: r.brand,
		model: r.model,
		productVariant: r.product_variant,
		generationTier: r.generation_tier,
		retailer: r.retailer,
		variantName: r.variant_name,
		listingUrl: r.listing_url,
		status: r.status,
		lastSnapshotAt: r.last_snapshot_at,
		latestDate: r.latest_date,
		latestPrice: r.latest_price,
		latestStock: r.latest_stock,
		latestScrapedAt: r.latest_scraped_at,
		windowStartDate: r.window_start_date,
		windowStartPrice: r.window_start_price,
		pointsInWindow: r.points_in_window
	}));
}

export function getSparklines(
	db: DB,
	listingIds: number[],
	days = DEFAULT_WINDOW_DAYS
): Map<number, SparklinePoint[]> {
	if (listingIds.length === 0) return new Map();
	const placeholders = listingIds.map(() => '?').join(',');
	const rows = db
		.prepare(
			`SELECT retailer_listing_id AS listingId, snapshot_date AS date, price_aud AS price
			 FROM price_snapshots
			 WHERE retailer_listing_id IN (${placeholders})
			   AND snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), ?)
			 ORDER BY retailer_listing_id, snapshot_date ASC`
		)
		.all(...listingIds, `-${days} days`) as SparklinePoint[];

	const byListing = new Map<number, SparklinePoint[]>();
	for (const row of rows) {
		const arr = byListing.get(row.listingId) ?? [];
		arr.push(row);
		byListing.set(row.listingId, arr);
	}
	return byListing;
}
