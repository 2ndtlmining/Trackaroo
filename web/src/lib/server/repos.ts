import { statSync } from 'node:fs';
import type { DB, ListingRow, ProductRow, SpecRow, SnapshotRow } from './db';
import type {
	Category,
	GenerationTier,
	ListingFilters,
	ListingSort,
	ListingStatus,
	Retailer,
	StockStatus
} from '../types';

export const DEFAULT_WINDOW_DAYS = 7;
export const MIN_HISTORY_POINTS = 3;

export interface Summary {
	trackedProducts: number;
	listingsToday: number;
	retailerCount: number;
	latestSnapshotDate: string | null;
	snapshotCount: number;
	snapshotDays: number;
	dbSizeBytes: number;
	biggestMover: Mover | null;
}
export interface SparklinePoint {
	listingId: number;
	date: string;
	price: number;
}

// Product-level price series (cheapest in-stock per day) for card sparklines.
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
	// Cheapest in-stock price per day across the product's listings (for the
	// unexpanded card sparkline); empty when no in-stock history in the window.
	sparkline?: PricePoint[];
}

// Groups per-listing rows into one entry per product (for the Products card
// grid). `sort` reorders the groups: price sorts order by cheapest in-stock
// price (products with nothing in stock always sink to the end); the default
// keeps the row order the SQL produced (category, model).
export function groupListingsByProduct(
	listings: LatestListing[],
	sort: ListingSort | undefined = undefined
): ProductGroup[] {
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

	const groups = [...byProduct.values()];
	if (sort === 'price-asc' || sort === 'price-desc') {
		const dir = sort === 'price-asc' ? 1 : -1;
		groups.sort((a, b) => {
			if (a.cheapestInStockPrice === null && b.cheapestInStockPrice === null) {
				return a.model.localeCompare(b.model);
			}
			if (a.cheapestInStockPrice === null) return 1;
			if (b.cheapestInStockPrice === null) return -1;
			return dir * (a.cheapestInStockPrice - b.cheapestInStockPrice) || a.model.localeCompare(b.model);
		});
	}
	return groups;
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
}

// Canonical display names for AIB/GPU partner brands, keyed by the lowercase
// first token of the retailer variant name (e.g. "Gigabyte GeForce RTX 5060
// Windforce OC GDDR7 8GB" -> "Gigabyte"). Used to group the per-product
// listings panel by brand. Unknown prefixes fall back to the product brand.
export { AIB_BRAND_ALIASES, deriveListingBrand } from '$lib/branding';

// Excludes CPU+motherboard bundle listings (e.g. Scorptec "... power bundle")
// from product pricing. Bundles price the whole combo, not the component alone,
// so they'd throw off CPU-only price listings, movers, and history.
function notBundle(alias: string): string {
	return `
	lower(${alias}.variant_name) NOT LIKE '%bundle%'
	AND lower(${alias}.variant_name) NOT LIKE '%combo%'
	AND lower(${alias}.listing_url) NOT LIKE '%bundle%'
	AND lower(${alias}.listing_url) NOT LIKE '%bdl-%'
`;
}

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
	if (filters.retailer) {
		clauses.push('l.retailer = @retailer');
		params.retailer = filters.retailer;
	}
	if (filters.brand) {
		clauses.push('p.brand = @brand');
		params.brand = filters.brand;
	}
	if (filters.generation_tier) {
		clauses.push('p.generation_tier = @tier');
		params.tier = filters.generation_tier;
	}
	if (filters.query) {
		clauses.push('(p.model LIKE @q OR p.brand LIKE @q OR p.variant LIKE @q OR l.variant_name LIKE @q)');
		params.q = `%${filters.query}%`;
	}
	return { clause: clauses.length ? ` AND ${clauses.join(' AND ')}` : '', params };
}

function sortClause(sort: ListingSort | undefined): string {
	switch (sort) {
		case 'price-asc':
			return 'ORDER BY lat.price_aud ASC, p.category, p.model, l.retailer';
		case 'price-desc':
			return 'ORDER BY lat.price_aud DESC, p.category, p.model, l.retailer';
		default:
			return 'ORDER BY p.category, p.model, l.retailer, lat.price_aud';
	}
}

export function getBrands(db: DB): string[] {
	const rows = db
		.prepare('SELECT DISTINCT brand FROM products WHERE tracked = 1 ORDER BY brand ASC')
		.all() as Array<{ brand: string }>;
	return rows.map((r) => r.brand);
}

export interface ProductIndexEntry {
	id: number;
	category: Category;
	brand: string;
	model: string;
	productVariant: string | null;
	// Total price snapshots across the product's listings — lets the palette
	// show which products actually have price history yet.
	snapshotCount: number;
}

export function getProductIndex(db: DB): ProductIndexEntry[] {
	return db
		.prepare(
			`SELECT p.id, p.category, p.brand, p.model, p.variant AS productVariant,
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

export interface HeaderStats {
	latestSnapshotDate: string | null;
	earliestSnapshotDate: string | null;
	snapshotCount: number;
	snapshotDays: number;
	dbSizeBytes: number;
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

export function getSummary(db: DB): Summary {
	const tracked = db.prepare('SELECT COUNT(*) AS n FROM products WHERE tracked = 1').get() as {
		n: number;
	};

	const latestDateRow = db
		.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots')
		.get() as { d: string | null };

	let listingsToday = 0;
	if (latestDateRow.d) {
		const today = db
			.prepare(
				'SELECT COUNT(DISTINCT retailer_listing_id) AS n FROM price_snapshots WHERE snapshot_date = ?'
			)
			.get(latestDateRow.d) as { n: number };
		listingsToday = today.n;
	}

	const retailers = db
		.prepare(
			"SELECT COUNT(DISTINCT retailer) AS n FROM retailer_listings WHERE status = 'active'"
		)
		.get() as { n: number };

	const header = getHeaderStats(db);

	const best = getMovers(db, 1).find((m) => !m.notEnoughHistory && m.pctChange !== null) ?? null;

	return {
		trackedProducts: tracked.n,
		listingsToday,
		retailerCount: retailers.n,
		latestSnapshotDate: header.latestSnapshotDate,
		snapshotCount: header.snapshotCount,
		snapshotDays: header.snapshotDays,
		dbSizeBytes: header.dbSizeBytes,
		biggestMover: best
	};
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
		${sortClause(filters.sort)}
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

// Cheapest in-stock price per day for each product (single query, windowed on
// the DB max date like getSparklines). Powers the unexpanded card sparkline so
// the card grid shows the tracked price trend at a glance.
export function getProductSparklines(
	db: DB,
	productIds: number[],
	days = DEFAULT_WINDOW_DAYS
): Map<number, PricePoint[]> {
	if (productIds.length === 0) return new Map();
	const placeholders = productIds.map(() => '?').join(',');
	const rows = db
		.prepare(
			`SELECT l.product_id AS productId, s.snapshot_date AS date, MIN(s.price_aud) AS price
			 FROM retailer_listings l
			 JOIN price_snapshots s ON s.retailer_listing_id = l.id
			 WHERE l.product_id IN (${placeholders})
			   AND s.stock_status = 'in_stock'
			   AND ${notBundle('l')}
			   AND s.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), ?)
			 GROUP BY l.product_id, s.snapshot_date
			 ORDER BY l.product_id, s.snapshot_date ASC`
		)
		.all(...productIds, `-${days} days`) as Array<{
		productId: number;
		date: string;
		price: number;
	}>;

	const byProduct = new Map<number, PricePoint[]>();
	for (const row of rows) {
		const arr = byProduct.get(row.productId) ?? [];
		arr.push({ date: row.date, price: row.price });
		byProduct.set(row.productId, arr);
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
		.prepare(
			`SELECT s.snapshot_date AS date, MIN(s.price_aud) AS price
			FROM retailer_listings l
			JOIN price_snapshots s ON s.retailer_listing_id = l.id
			WHERE l.product_id = ? AND s.stock_status = 'in_stock' AND ${notBundle('l')}
			  AND s.snapshot_date = (SELECT MAX(snapshot_date) FROM price_snapshots)
			GROUP BY s.snapshot_date`
		)
		.get(productId) as { date: string; price: number } | undefined;

	return rows.map((r) => ({
		date: r.date,
		low: r.low,
		high: r.high,
		cheapestInStock: latest && latest.date === r.date ? latest.price : null
	}));
}

export function getProductHistory(db: DB, productId: number): ProductHistory | null {
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
		band: getPriceBand(db, productId)
	};
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
}

// Lowest/highest in-stock price for a product over the trailing window,
// anchored to the latest snapshot day so results are deterministic regardless
// of wall-clock. Excludes CPU+motherboard bundles like the band query.
export function getPriceExtremes(
	db: DB,
	productId: number,
	days = 90
): { low: number | null; high: number | null } {
	const row = db
		.prepare(
			`SELECT
				MIN(s.price_aud) AS low,
				MAX(s.price_aud) AS high
			FROM retailer_listings l
			JOIN price_snapshots s ON s.retailer_listing_id = l.id
			WHERE l.product_id = ?
			  AND s.stock_status = 'in_stock'
			  AND ${notBundle('l')}
			  AND s.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), ?)`
		)
		.get(productId, `-${days} days`) as { low: number | null; high: number | null };
	return { low: row.low, high: row.high };
}

export function getCheapestPerModel(db: DB, category: Category): CheapestListing[] {
	const rows = db
		.prepare(
			`SELECT
				p.id AS product_id,
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
				   AND ps3.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), '-90 days')) AS high90
			FROM products p
			JOIN retailer_listings l ON l.product_id = p.id AND l.status = 'active'
			JOIN price_snapshots ps
			  ON ps.retailer_listing_id = l.id
			  AND ps.snapshot_date = (SELECT MAX(snapshot_date) FROM price_snapshots)
			  AND ps.stock_status = 'in_stock'
			WHERE p.category = @category
			  AND p.tracked = 1
			  AND ${notBundle('l')}
			  AND ps.price_aud = (
				SELECT MIN(ps2.price_aud)
				FROM price_snapshots ps2
				JOIN retailer_listings l2 ON l2.id = ps2.retailer_listing_id
				WHERE l2.product_id = p.id
				  AND l2.status = 'active'
				  AND ${notBundle('l2')}
				  AND ps2.snapshot_date = ps.snapshot_date
				  AND ps2.stock_status = 'in_stock'
			  )
			GROUP BY p.id
			ORDER BY p.model COLLATE NOCASE ASC`
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
		ninetyDayHigh: r.high90
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