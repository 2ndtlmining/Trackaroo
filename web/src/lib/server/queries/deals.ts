import type { DB } from '../db';
import type { Category, Retailer } from '../../types';
import { cheapestListingPerProduct, dailyCheapestInStock, notBundle } from './sql';
import type { CheapestListing, DealCandidate } from '../../models';

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
