// 90-day price range per product, for the segmented range bar (#22). Built on
// the shared daily-cheapest fragment so it counts the same prices as the
// sparkline and headline: in stock, not a bundle, on an active listing.
import type { DB } from '../db';
import { memo } from '../cache';
import { dailyCheapestInStock } from './sql';

export interface Range90 {
	low: number;
	high: number;
}

// Low and high of the daily cheapest price over the last 90 days (global
// latest snapshot date minus 89 days, inclusive). One grouped query over the
// whole DB, memoised; productIds only narrows the returned map. A product
// with no in-window history is absent.
export function getRange90(db: DB, productIds?: number[]): Map<number, Range90> {
	const all = memo(db, 'range90', () => {
		const rows = db
			.prepare(
				`SELECT d.product_id AS productId, MIN(d.price) AS low, MAX(d.price) AS high
				 FROM (${dailyCheapestInStock({
						form: 'standalone',
						perProduct: true,
						activeOnly: true,
						window: `'-89 days'`
					})}) d
				 GROUP BY d.product_id`
			)
			.all() as Array<{ productId: number; low: number; high: number }>;
		return new Map(rows.map((r) => [r.productId, { low: r.low, high: r.high }]));
	});
	if (!productIds) return all;
	const out = new Map<number, Range90>();
	for (const id of productIds) {
		const r = all.get(id);
		if (r) out.set(id, r);
	}
	return out;
}
