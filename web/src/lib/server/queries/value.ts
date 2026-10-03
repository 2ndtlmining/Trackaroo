import type { DB } from '../db';
import { memo } from '../cache';
import { cheapestListingPerProduct } from './sql';
import { perfFor, type MetricKey } from '../../perfIndex';
import { valueCoverage, type ValuePoint } from '../../value';
import type { ValueCoverage, ValueRow } from '../../models';

/**
 * Tracked products of a category with the cheapest in-stock active non-bundle
 * price on the latest snapshot date, or null when nothing is in stock.
 */
export function getValueRows(db: DB, category: 'gpu' | 'cpu'): ValueRow[] {
	return memo(db, `valueRows:${category}`, () => {
		const products = db
			.prepare(
				`SELECT id, model, vram_gb FROM products
				 WHERE category = @category AND tracked = 1
				 ORDER BY model COLLATE NOCASE ASC`
			)
			.all({ category }) as { id: number; model: string; vram_gb: number | null }[];
		const prices = new Map(
			(
				db
					.prepare(cheapestListingPerProduct('p.id AS product_id, ps.price_aud AS price', 'p.category = @category'))
					.all({ category }) as { product_id: number; price: number }[]
			).map((r) => [r.product_id, r.price])
		);
		return products.map((p) => ({
			id: p.id,
			name: p.model,
			model: p.model,
			vramGb: p.vram_gb,
			price: prices.get(p.id) ?? null
		}));
	});
}

export interface ValueData {
	points: ValuePoint[];
	coverage: ValueCoverage;
}

/** Chartable points for a metric plus the coverage counts (R6). */
export function getValueData(db: DB, category: 'gpu' | 'cpu', metric: MetricKey): ValueData {
	const rows = getValueRows(db, category).map((r) => ({
		r,
		perf: perfFor({ category, model: r.model, vramGb: r.vramGb }, metric)
	}));
	const points: ValuePoint[] = [];
	for (const { r, perf } of rows) {
		if (perf != null && perf > 0 && r.price != null && r.price > 0) {
			points.push({ id: r.id, name: r.name, price: r.price, perf, vramGb: r.vramGb });
		}
	}
	return { points, coverage: valueCoverage(rows.map(({ r, perf }) => ({ price: r.price, perf }))) };
}
