import type { DB, ListingRow, ProductRow, SnapshotRow } from '../db';
import type { ListingStatus, Retailer, StockStatus } from '../../types';
import { dailyCheapestInStock, notBundle } from './sql';
import type { PriceBandPoint, ProductHistory, SpecRow } from '../../models';
import { getProductStats } from './stats';

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
