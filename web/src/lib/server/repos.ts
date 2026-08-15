import type { DB, ListingRow, ProductRow, SnapshotRow } from './db';
import type {
	Category,
	GenerationTier,
	ListingFilters,
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
	biggestMover: Mover | null;
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
}

export interface Series {
	listing: ListingRow;
	points: SnapshotRow[];
}

export interface ProductHistory {
	product: ProductRow;
	series: Series[];
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
	return { clause: clauses.length ? ` AND ${clauses.join(' AND ')}` : '', params };
}

export function getBrands(db: DB): string[] {
	const rows = db
		.prepare('SELECT DISTINCT brand FROM products WHERE tracked = 1 ORDER BY brand ASC')
		.all() as Array<{ brand: string }>;
	return rows.map((r) => r.brand);
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

	const best = getMovers(db, 1).find((m) => !m.notEnoughHistory && m.pctChange !== null) ?? null;

	return {
		trackedProducts: tracked.n,
		listingsToday,
		retailerCount: retailers.n,
		latestSnapshotDate: latestDateRow.d,
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
		WHERE l.status = 'active' AND p.tracked = 1${clause}
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
			WHERE l.product_id = ?
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

	return {
		product,
		series: [...listings.values()].map(({ listing, points }) => ({ listing, points }))
	};
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
		WHERE l.status = 'active' AND p.tracked = 1
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