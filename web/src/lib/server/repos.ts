import { statSync } from 'node:fs';
import type { DB, ListingRow, ProductRow, SnapshotRow } from './db';
import type {
	AlertChannel,
	Category,
	GenerationTier,
	ListingFilters,
	ListingStatus,
	Retailer,
	StockStatus
} from '../types';
import { MIN_HISTORY_POINTS } from '../constants';
import { dailyCheapestInStock, cheapestListingPerProduct, notBundle } from './queries/sql';
import type {
	AlertRow,
	CheapestListing,
	CompareEntry,
	ComparePrice,
	DealCandidate,
	HeaderStats,
	LatestListing,
	Mover,
	PriceBandPoint,
	ProductGroup,
	ProductHistory,
	ProductIndexEntry,
	ProductMove,
	ProductStats,
	RetailerFreshness,
	SparklinePoint,
	SpecRow,
	TrackedProduct
} from '../models';
export type * from '../models';

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

const LATEST_CTE = `
	WITH latest AS (
		SELECT s.*
		FROM price_snapshots s
		JOIN (
			SELECT retailer_listing_id, MAX(snapshot_date) AS max_date
			FROM price_snapshots
			GROUP BY retailer_listing_id
		) m ON m.retailer_listing_id = s.retailer_listing_id
		  AND m.max_date = s.snapshot_date
	)
`;

function windowStartSubquery(reference: string): string {
	return `(
		SELECT MIN(ps.snapshot_date)
		FROM price_snapshots ps
		WHERE ps.retailer_listing_id = lat.retailer_listing_id
		  AND ps.snapshot_date >= date(${reference}, @window)
		  AND ps.snapshot_date < ${reference}
	)`;
}

function windowStartPriceSubquery(reference: string): string {
	return `(
		SELECT ps.price_aud
		FROM price_snapshots ps
		WHERE ps.retailer_listing_id = lat.retailer_listing_id
		  AND ps.snapshot_date = ${windowStartSubquery(reference)}
		LIMIT 1
	)`;
}

function pointsInWindowSubquery(reference: string): string {
	return `(
		SELECT COUNT(*)
		FROM price_snapshots ps
		WHERE ps.retailer_listing_id = lat.retailer_listing_id
		  AND ps.snapshot_date >= date(${reference}, @window)
		  AND ps.snapshot_date <= ${reference}
	)`;
}

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

function dbFileSize(db: DB): number {
	try {
		const list = db.pragma('database_list', { simple: false }) as Array<{
			seq: number;
			name: string;
			file: string;
		}>;
		const main = list.find((d) => d.name === 'main');
		if (main?.file) return statSync(main.file).size;
	} catch {
		// Non-fatal — in-memory DBs have no backing file.
	}
	return 0;
}

export function getHeaderStats(db: DB): HeaderStats {
	const latestDateRow = db
		.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots')
		.get() as { d: string | null };
	const earliestDateRow = db
		.prepare('SELECT MIN(snapshot_date) AS d FROM price_snapshots')
		.get() as { d: string | null };
	const snaps = db.prepare('SELECT COUNT(*) AS n FROM price_snapshots').get() as { n: number };
	const snapDays = db
		.prepare('SELECT COUNT(DISTINCT snapshot_date) AS n FROM price_snapshots')
		.get() as { n: number };

	return {
		latestSnapshotDate: latestDateRow.d,
		earliestSnapshotDate: earliestDateRow.d,
		snapshotCount: snaps.n,
		snapshotDays: snapDays.n,
		dbSizeBytes: dbFileSize(db)
	};
}

// True when `name` is a table in this DB. The dashboard must keep rendering on a
// DB from before a migration ran (Review Focus 5).
export function tableExists(db: DB, name: string): boolean {
	return (
		db.prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?").get(name) !==
		undefined
	);
}

// Per-retailer currency for the homepage health strip and /healthz.
// The retailer list comes from active_retailers -- the pipeline's
// config.ACTIVE_RETAILERS mirrored into the DB -- so a retailer that has never
// written a row is listed as missing instead of silently absent (R1, 28-Sep:
// Umart on prod). A retailer that is no longer active but has history follows,
// by slug. On a DB without the table, retailers with data are listed by slug.
export function getRetailerFreshness(db: DB): RetailerFreshness[] {
	const latest = db
		.prepare(
			`SELECT l.retailer AS retailer, MAX(s.snapshot_date) AS latest
			 FROM retailer_listings l
			 JOIN price_snapshots s ON s.retailer_listing_id = l.id
			 GROUP BY l.retailer`
		)
		.all() as Array<{ retailer: string; latest: string | null }>;
	const latestBy = new Map(latest.map((r) => [r.retailer, r.latest]));

	const active = tableExists(db, 'active_retailers')
		? (
				db
					.prepare('SELECT retailer FROM active_retailers ORDER BY position, retailer')
					.all() as Array<{ retailer: string }>
			).map((r) => r.retailer)
		: [];
	const inactive = [...latestBy.keys()].filter((r) => !active.includes(r)).sort();

	// One GROUP BY pass, not a correlated MAX(id) subquery re-run per row
	// (final review M4) -- /healthz calls this on every health-strip request.
	const runs = tableExists(db, 'scrape_runs')
		? (db
				.prepare(
					`SELECT r.retailer AS retailer, r.finished_at AS at, r.status AS status, r.matched AS matched
					 FROM scrape_runs r
					 WHERE r.id IN (SELECT MAX(id) FROM scrape_runs GROUP BY retailer)`
				)
				.all() as Array<{ retailer: string; at: string; status: string; matched: number | null }>)
		: [];
	const runBy = new Map(runs.map((r) => [r.retailer, r]));

	return [...active, ...inactive].map((retailer) => {
		const run = runBy.get(retailer);
		return {
			retailer: retailer as Retailer,
			latestSnapshotDate: latestBy.get(retailer) ?? null,
			lastRunAt: run?.at ?? null,
			lastRunStatus: run?.status ?? null,
			lastRunMatched: run?.matched ?? null
		};
	});
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
	filters: ListingFilters = {},
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

export function getProductStats(db: DB, productId: number, days = 30): ProductStats {
	const row = db
		.prepare(
			`SELECT AVG(day_min.price) AS avg, COUNT(*) AS points
			 FROM (
				${dailyCheapestInStock({ form: 'standalone', product: '= ?', window: '?' })}
			 ) day_min`
		)
		// -(days - 1): an N-day window covers N dates inclusive of today, not
		// N+1 (#6/D4). Only this window arithmetic changes -- sparklines and
		// movers keep the old boundary on purpose.
		.get(productId, `-${days - 1} days`) as { avg: number | null; points: number };
	return { avg30: row.avg, avg30Points: row.points };
}

// Per-product 30-day stats for a list of products (single query) — powers the deal badges on the products grid.
export function getProductDealStats(
	db: DB,
	productIds: number[],
	days = 30
): Map<number, ProductStats> {
	if (productIds.length === 0) return new Map();
	const placeholders = productIds.map(() => '?').join(',');
	const rows = db
		.prepare(
			`SELECT day_min.product_id AS productId, AVG(day_min.price) AS avg, COUNT(*) AS points
			 FROM (
				${dailyCheapestInStock({ form: 'standalone', product: `IN (${placeholders})`, perProduct: true, window: '?' })}
			 ) day_min
			 GROUP BY day_min.product_id`
		)
		// -(days - 1): see getProductStats (#6/D4).
		.all(...productIds, `-${days - 1} days`) as Array<{
		productId: number;
		avg: number | null;
		points: number;
	}>;

	const byProduct = new Map<number, ProductStats>();
	for (const row of rows) {
		byProduct.set(row.productId, { avg30: row.avg, avg30Points: row.points });
	}
	return byProduct;
}

export function getPriceBand(db: DB, productId: number): PriceBandPoint[] {
	const rows = db
		.prepare(
			`SELECT
				s.snapshot_date AS date,
				MIN(CASE WHEN s.stock_status = 'in_stock' THEN s.price_aud END) AS low,
				MAX(CASE WHEN s.stock_status = 'in_stock' THEN s.price_aud END) AS high
			FROM retailer_listings l
			JOIN price_snapshots s ON s.retailer_listing_id = l.id
			WHERE l.product_id = ? AND ${notBundle('l')}
			GROUP BY s.snapshot_date
			ORDER BY s.snapshot_date`
		)
		.all(productId) as Array<{ date: string; low: number | null; high: number | null }>;

	const latest = db
		.prepare(dailyCheapestInStock({ form: 'standalone', product: '= ?', window: null, dateAs: 'date' }))
		.get(productId) as { date: string; price: number } | undefined;

	return rows.map((r) => ({
		date: r.date,
		low: r.low,
		high: r.high,
		cheapestInStock: latest && latest.date === r.date ? latest.price : null
	}));
}

// Latest snapshot_date per retailer, across all products -- lets the display
// layer tell "this listing's own retailer hasn't been scraped in days" (not
// stale) apart from "everyone else moved on and this one didn't" (#4). Pulled
// out of getProductHistory so the product loader can memoise it independently
// (#28): it scans price_snapshots in full and does not depend on productId.
export function getRetailerLatest(db: DB): Record<string, string> {
	return Object.fromEntries(
		(
			db
				.prepare(
					`SELECT l.retailer AS retailer, MAX(s.snapshot_date) AS latest
					 FROM price_snapshots s JOIN retailer_listings l ON l.id = s.retailer_listing_id
					 GROUP BY l.retailer`
				)
				.all() as Array<{ retailer: string; latest: string }>
		).map((r) => [r.retailer, r.latest])
	);
}

export function getProductHistory(
	db: DB,
	productId: number,
	retailerLatest?: Record<string, string>
): ProductHistory | null {
	const product = db.prepare('SELECT * FROM products WHERE id = ?').get(productId) as
		| ProductRow
		| undefined;
	if (!product) return null;

	const rows = db
		.prepare(
			`SELECT
				l.id AS lid, l.product_id, l.retailer, l.variant_name, l.retailer_sku,
				l.listing_url, l.status, l.first_seen_at, l.last_seen_at, l.last_snapshot_at,
				s.id AS sid, s.retailer_listing_id, s.snapshot_date, s.price_aud, s.stock_status, s.scraped_at
			FROM retailer_listings l
			LEFT JOIN price_snapshots s ON s.retailer_listing_id = l.id
			WHERE l.product_id = ? AND ${notBundle('l')}
			ORDER BY l.id, s.snapshot_date`
		)
		.all(productId) as Array<{
		lid: number;
		product_id: number;
		retailer: Retailer;
		variant_name: string | null;
		retailer_sku: string | null;
		listing_url: string;
		status: ListingStatus;
		first_seen_at: string;
		last_seen_at: string | null;
		last_snapshot_at: string | null;
		sid: number | null;
		retailer_listing_id: number | null;
		snapshot_date: string | null;
		price_aud: number | null;
		stock_status: string | null;
		scraped_at: string | null;
	}>;

	const listings = new Map<number, { listing: ListingRow; points: SnapshotRow[] }>();
	for (const r of rows) {
		let entry = listings.get(r.lid);
		if (!entry) {
			entry = {
				listing: {
					id: r.lid,
					product_id: r.product_id,
					retailer: r.retailer,
					variant_name: r.variant_name,
					retailer_sku: r.retailer_sku,
					listing_url: r.listing_url,
					status: r.status,
					first_seen_at: r.first_seen_at,
					last_seen_at: r.last_seen_at,
					last_snapshot_at: r.last_snapshot_at
				},
				points: []
			};
			listings.set(r.lid, entry);
		}
		if (r.sid !== null) {
			entry.points.push({
				id: r.sid,
				retailer_listing_id: r.retailer_listing_id!,
				snapshot_date: r.snapshot_date!,
				price_aud: r.price_aud!,
				stock_status: r.stock_status as StockStatus,
				scraped_at: r.scraped_at!
			});
		}
	}

	// Specs are fetched only on the product detail page — never joined into
	// list/index queries (IMPROVEMENT_16 §7.3).
	const spec = db
		.prepare('SELECT * FROM specs WHERE product_id = ? ORDER BY last_synced_at DESC LIMIT 1')
		.get(productId) as SpecRow | undefined;

	return {
		product,
		series: [...listings.values()].map(({ listing, points }) => ({ listing, points })),
		specs: spec ?? null,
		band: getPriceBand(db, productId),
		stats: getProductStats(db, productId),
		retailerLatest: retailerLatest ?? getRetailerLatest(db)
	};
}

export function getCheapestPerModel(db: DB, category: Category): CheapestListing[] {
	// Fixed 30-day literal here, unlike getDealCandidates' bound -(days - 1) window.
	const daily30 = { form: 'correlated', product: '= p.id', window: "'-30 days'" } as const;
	const rows = db
		.prepare(
			cheapestListingPerProduct(
				`p.id AS product_id,
				p.model,
				p.brand,
				l.variant_name,
				l.retailer,
				ps.price_aud AS price,
				ps.snapshot_date,
				(SELECT MIN(ps3.price_aud)
				 FROM price_snapshots ps3
				 JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
				 WHERE l3.product_id = p.id
				   AND ps3.stock_status = 'in_stock'
				   AND ${notBundle('l3')}
				   AND ps3.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), '-90 days')) AS low90,
				(SELECT MAX(ps3.price_aud)
				 FROM price_snapshots ps3
				 JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
				 WHERE l3.product_id = p.id
				   AND ps3.stock_status = 'in_stock'
				   AND ${notBundle('l3')}
				   AND ps3.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), '-90 days')) AS high90,
				(SELECT AVG(dm.price)
				 FROM (
					${dailyCheapestInStock(daily30)}
				 ) dm) AS avg30,
				(SELECT COUNT(*)
				 FROM (
					${dailyCheapestInStock({ ...daily30, dateOnly: true })}
				 ) dm) AS avg30_points`,
				'p.category = @category'
			)
		)
		.all({ category }) as Array<{
		product_id: number;
		model: string;
		brand: string;
		variant_name: string | null;
		retailer: Retailer;
		price: number;
		snapshot_date: string;
		low90: number | null;
		high90: number | null;
		avg30: number | null;
		avg30_points: number;
	}>;

	return rows.map((r) => ({
		productId: r.product_id,
		model: r.model,
		brand: r.brand,
		variantName: r.variant_name,
		retailer: r.retailer,
		price: r.price,
		snapshotDate: r.snapshot_date,
		ninetyDayLow: r.low90,
		ninetyDayHigh: r.high90,
		avg30: r.avg30,
		avg30Points: r.avg30_points
	}));
}

// One row per tracked product: its cheapest in-stock listing on the latest
// snapshot date, plus the two history figures /deals ranks on. Spans both
// categories in a single query — the page facets by category from the URL, so
// splitting it per category would just double the work.
export function getDealCandidates(db: DB, days = 30): DealCandidate[] {
	const daily = { form: 'correlated', product: '= p.id', window: '@window' } as const;
	const rows = db
		.prepare(
			cheapestListingPerProduct(
				`p.id AS product_id,
				p.category,
				p.model,
				p.brand,
				l.id AS listing_id,
				l.variant_name,
				l.retailer,
				l.listing_url,
				ps.price_aud AS price,
				ps.snapshot_date,
				(SELECT MIN(ps3.price_aud)
				 FROM price_snapshots ps3
				 JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
				 WHERE l3.product_id = p.id
				   AND ps3.stock_status = 'in_stock'
				   AND ${notBundle('l3')}) AS all_time_low,
				(SELECT AVG(dm.price)
				 FROM (
					${dailyCheapestInStock(daily)}
				 ) dm) AS avg30,
				(SELECT COUNT(*)
				 FROM (
					${dailyCheapestInStock({ ...daily, dateOnly: true })}
				 ) dm) AS avg30_points,
				(SELECT MAX(dm.price)
				 FROM (
					${dailyCheapestInStock(daily)}
				 ) dm) AS window_high,
				(SELECT MIN(ps3.snapshot_date)
				 FROM price_snapshots ps3
				 JOIN retailer_listings l3 ON l3.id = ps3.retailer_listing_id
				 WHERE l3.product_id = p.id
				   AND ps3.stock_status = 'in_stock'
				   AND ${notBundle('l3')}) AS history_start`
			)
		)
		// -(days - 1): see getProductStats (#6/D4).
		.all({ window: `-${days - 1} days` }) as Array<{
		product_id: number;
		category: Category;
		model: string;
		brand: string;
		listing_id: number;
		variant_name: string | null;
		retailer: Retailer;
		listing_url: string;
		price: number;
		snapshot_date: string;
		all_time_low: number | null;
		avg30: number | null;
		avg30_points: number;
		window_high: number | null;
		history_start: string | null;
	}>;

	return rows.map((r) => ({
		productId: r.product_id,
		category: r.category,
		model: r.model,
		brand: r.brand,
		listingId: r.listing_id,
		variantName: r.variant_name,
		retailer: r.retailer,
		listingUrl: r.listing_url,
		price: r.price,
		snapshotDate: r.snapshot_date,
		allTimeLow: r.all_time_low,
		avg30: r.avg30,
		avg30Points: r.avg30_points,
		windowHigh: r.window_high,
		historyStart: r.history_start
	}));
}

export function getMovers(db: DB, windowDays: number): Mover[] {
	const sql = `
${LATEST_CTE}
		SELECT
			p.id AS product_id,
			p.category,
			p.brand,
			p.model,
			l.id AS listing_id,
			l.retailer,
			l.variant_name,
			l.listing_url,
			lat.price_aud AS new_price,
			lat.snapshot_date AS window_end,
			${windowStartSubquery('lat.snapshot_date')} AS window_start,
			${windowStartPriceSubquery('lat.snapshot_date')} AS old_price,
			${pointsInWindowSubquery('lat.snapshot_date')} AS points_in_window,
			(
				SELECT COUNT(*)
				FROM price_snapshots ps
				WHERE ps.retailer_listing_id = lat.retailer_listing_id
			) AS history_points
		FROM latest lat
		JOIN retailer_listings l ON l.id = lat.retailer_listing_id
		JOIN products p ON p.id = l.product_id
		WHERE l.status = 'active' AND p.tracked = 1 AND ${notBundle('l')}
	`;

	const rows = db.prepare(sql).all({ window: `-${windowDays} days` }) as Array<{
		product_id: number;
		category: Category;
		brand: string;
		model: string;
		listing_id: number;
		retailer: Retailer;
		variant_name: string | null;
		listing_url: string;
		new_price: number;
		window_end: string;
		window_start: string | null;
		old_price: number | null;
		points_in_window: number;
		history_points: number;
	}>;

	return rows
		.map((r) => {
			const change =
				r.old_price !== null ? Math.round((r.new_price - r.old_price) * 100) / 100 : null;
			const pctChange =
				r.old_price !== null && r.old_price > 0
					? Math.round(((r.new_price - r.old_price) / r.old_price) * 1000) / 10
					: null;
			return {
				listingId: r.listing_id,
				productId: r.product_id,
				category: r.category,
				brand: r.brand,
				model: r.model,
				retailer: r.retailer,
				variantName: r.variant_name,
				listingUrl: r.listing_url,
				oldPrice: r.old_price,
				newPrice: r.new_price,
				change,
				pctChange,
				pointsInWindow: r.points_in_window,
				historyPoints: r.history_points,
				notEnoughHistory: r.history_points < MIN_HISTORY_POINTS,
				windowStart: r.window_start,
				windowEnd: r.window_end
			};
		})
		.sort((a, b) => {
			const av = a.pctChange !== null ? Math.abs(a.pctChange) : -1;
			const bv = b.pctChange !== null ? Math.abs(b.pctChange) : -1;
			return bv - av;
		});
}

// Product-level moves for the homepage (D7): the cheapest in-stock price per
// day, on the first day inside the window vs the latest snapshot day. The
// per-listing movers let one premium SKU rising headline "Biggest rises" while
// the price a buyer actually pays -- the product's cheapest -- was falling.
// The window boundary matches getMovers (`>= latest - N days`). A product
// needs MIN_HISTORY_POINTS days in that series, as the per-listing rows did
// (their notEnoughHistory), so a 2-day product is never a "biggest drop".
export function getProductMoves(db: DB, windowDays: number): ProductMove[] {
	const rows = db
		.prepare(
			`WITH maxd AS (SELECT MAX(snapshot_date) AS d FROM price_snapshots),
			day_min AS (
				${dailyCheapestInStock({ form: 'standalone', perProduct: true, window: '@window', dateAs: 'date', anchor: '(SELECT d FROM maxd)' })}
			),
			ends AS (
				SELECT product_id, MIN(date) AS first, MAX(date) AS last
				FROM day_min
				GROUP BY product_id
				-- Thin history is never summarised (Review Focus 1): the series
				-- must span MIN_HISTORY_POINTS distinct in-stock days in the window.
				HAVING COUNT(*) >= @minPoints
			),
			moves AS (
				SELECT p.id AS product_id, p.category, p.brand, p.model,
				       e.first AS from_date, e.last AS to_date,
				       a.price AS old_price, b.price AS new_price,
				       (SELECT l2.id
				          FROM retailer_listings l2
				          JOIN price_snapshots s2 ON s2.retailer_listing_id = l2.id
				         WHERE l2.product_id = p.id
				           AND s2.snapshot_date = e.last
				           AND s2.stock_status = 'in_stock'
				           AND ${notBundle('l2')}
				         ORDER BY s2.price_aud, l2.id
				         LIMIT 1) AS listing_id
				FROM ends e
				JOIN products p ON p.id = e.product_id AND p.tracked = 1
				JOIN day_min a ON a.product_id = e.product_id AND a.date = e.first
				JOIN day_min b ON b.product_id = e.product_id AND b.date = e.last
				WHERE e.last = (SELECT d FROM maxd) AND e.first < e.last
			)
			SELECT m.*, l.retailer, l.variant_name
			FROM moves m
			JOIN retailer_listings l ON l.id = m.listing_id`
		)
		.all({ window: `-${windowDays} days`, minPoints: MIN_HISTORY_POINTS }) as Array<{
		product_id: number;
		category: Category;
		brand: string;
		model: string;
		from_date: string;
		to_date: string;
		old_price: number;
		new_price: number;
		retailer: Retailer;
		variant_name: string | null;
	}>;

	return rows.map((r) => ({
		productId: r.product_id,
		category: r.category,
		brand: r.brand,
		model: r.model,
		oldPrice: r.old_price,
		newPrice: r.new_price,
		change: Math.round((r.new_price - r.old_price) * 100) / 100,
		pctChange:
			r.old_price > 0 ? Math.round(((r.new_price - r.old_price) / r.old_price) * 1000) / 10 : 0,
		fromDate: r.from_date,
		toDate: r.to_date,
		retailer: r.retailer,
		variantName: r.variant_name
	}));
}

// Read-only view powering the /compare route: joins products + specs + each
// listing's latest in-stock price (per-listing, so a retailer that missed the
// latest day still contributes its real price). No schema changes required.
export function getComparisonData(db: DB, productIds: number[]): CompareEntry[] {
	const hasData = db.prepare('SELECT 1 AS ok FROM price_snapshots LIMIT 1').get();
	if (!hasData) return [];

	const productStmt = db.prepare('SELECT * FROM products WHERE id = ?');
	const specStmt = db.prepare(
		'SELECT * FROM specs WHERE product_id = ? ORDER BY last_synced_at DESC LIMIT 1'
	);
	const priceStmt = db.prepare(
		`${LATEST_CTE}
		SELECT l.retailer AS retailer, MIN(lat.price_aud) AS price
		FROM retailer_listings l
		JOIN latest lat ON lat.retailer_listing_id = l.id
		WHERE l.product_id = ? AND lat.stock_status = 'in_stock'
		  AND l.status = 'active'
		  AND ${notBundle('l')}
		GROUP BY l.retailer`
	);

	return productIds
		.map((id): CompareEntry | null => {
			const product = productStmt.get(id) as ProductRow | undefined;
			if (!product) return null;
			const spec = (specStmt.get(id) as SpecRow | undefined) ?? null;
			const priceRows = priceStmt.all(id) as Array<{
				retailer: Retailer;
				price: number;
			}>;
			const prices: ComparePrice[] = priceRows.map((r) => ({ retailer: r.retailer, price: r.price }));
			let cheapest: CompareEntry['cheapestInStock'] = null;
			for (const p of prices) {
				if (p.price !== null && (cheapest === null || p.price < cheapest.price)) {
					cheapest = { price: p.price, retailer: p.retailer };
				}
			}
			return { product, spec, prices, cheapestInStock: cheapest };
		})
		.filter((e): e is CompareEntry => e !== null);
}

// One alert per (product, channel). Re-arming an existing (product, channel)
// updates its target/restock flag and re-activates it rather than stacking a
// duplicate row. Cooldown columns are managed by check_alerts.py, never here.
export function upsertAlert(
	db: DB,
	productId: number,
	targetPrice: number,
	channel: AlertChannel,
	notifyOnRestock: boolean
): void {
	db.prepare(
		`INSERT INTO price_alerts (product_id, target_price, channel, notify_on_restock, active)
		 VALUES (?, ?, ?, ?, 1)
		 ON CONFLICT (product_id, channel)
		 DO UPDATE SET target_price = excluded.target_price,
		               notify_on_restock = excluded.notify_on_restock,
		               active = 1`
	).run(productId, targetPrice, channel, notifyOnRestock ? 1 : 0);
}

export function deleteAlert(db: DB, alertId: number): void {
	db.prepare('DELETE FROM price_alerts WHERE id = ?').run(alertId);
}

export function getProductAlerts(db: DB, productId: number): AlertRow[] {
	return db
		.prepare(
			`SELECT id, product_id, target_price, channel, notify_on_restock, active,
			        last_notified_at, last_notified_price, created_at
			 FROM price_alerts
			 WHERE product_id = ?
			 ORDER BY channel`
		)
		.all(productId) as AlertRow[];
}