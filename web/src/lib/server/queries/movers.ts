import type { DB } from '../db';
import type { Category, Retailer } from '../../types';
import { MIN_HISTORY_POINTS } from '../../constants';
import {
	LATEST_CTE,
	dailyCheapestInStock,
	notBundle,
	pointsInWindowSubquery,
	windowStartPriceSubquery,
	windowStartSubquery
} from './sql';
import type { Mover, ProductMove } from '../../models';

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
