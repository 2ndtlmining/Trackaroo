import type { DB } from '../db';
import { memo } from '../cache';
import { LATEST_WITH_RETAILER_CTE, cheapestInStockLatest, notBundle, seenRecently } from './sql';
import { perfFor, type MetricKey } from '../../perfIndex';
import { tierCoverage, valueCoverage, type ValuePoint } from '../../value';
import type { ValueCoverage, ValueRow } from '../../models';

interface ProductRow {
	id: number;
	brand: string;
	model: string;
	vram_gb: number | null;
	generation_tier: string | null;
}

/**
 * Tracked products of a category with their cheapest in-stock price, by the
 * catalogue's rule (each listing at its latest snapshot; see
 * cheapestInStockLatest), or null when nothing is in stock.
 */
export function getValueRows(db: DB, category: 'gpu' | 'cpu'): ValueRow[] {
	return memo(db, `valueRows:${category}`, () => {
		const products = db
			.prepare(
				`SELECT id, brand, model, vram_gb, generation_tier FROM products
				 WHERE category = @category AND tracked = 1
				 ORDER BY model COLLATE NOCASE ASC`
			)
			.all({ category }) as ProductRow[];
		const prices = new Map(
			(
				db
					.prepare(cheapestInStockLatest('p.category = @category'))
					.all({ category }) as { product_id: number; price: number }[]
			).map((r) => [r.product_id, r.price])
		);
		return products.map((p) => ({
			id: p.id,
			brand: p.brand,
			name: p.model,
			model: p.model,
			vramGb: p.vram_gb,
			tier: p.generation_tier,
			price: prices.get(p.id) ?? null
		}));
	});
}

/**
 * Retailers with an in-stock latest price for this category (the catalogue's
 * rule): the "cheapest in stock across ..." list on /value, in pipeline order.
 */
export function getValueRetailers(db: DB, category: 'gpu' | 'cpu'): string[] {
	return memo(db, `valueRetailers:${category}`, () =>
		(
			db
				.prepare(
					`${LATEST_WITH_RETAILER_CTE}
					 SELECT l.retailer AS retailer
					 FROM latest lat
					 JOIN retailer_listings l ON l.id = lat.retailer_listing_id
					 JOIN products p ON p.id = l.product_id
					 LEFT JOIN active_retailers a ON a.retailer = l.retailer
					 WHERE p.category = @category AND p.tracked = 1 AND l.status = 'active'
					   AND lat.stock_status = 'in_stock'
					   AND ${notBundle('l')}
					   AND ${seenRecently('lat', 'l')}
					 GROUP BY l.retailer
					 ORDER BY MIN(COALESCE(a.position, 999)), l.retailer`
				)
				.all({ category }) as { retailer: string }[]
		).map((r) => r.retailer)
	);
}

export interface ValueData {
	points: ValuePoint[];
	coverage: ValueCoverage;
	/** Coverage over the required tiers only (current and current-1). */
	required: { tracked: number; withPerf: number };
	retailers: string[];
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
			points.push({
				id: r.id,
				name: r.name,
				price: r.price,
				perf,
				vramGb: r.vramGb
			});
		}
	}
	return {
		points,
		coverage: valueCoverage(rows.map(({ r, perf }) => ({ price: r.price, perf }))),
		required: tierCoverage(rows.map(({ r, perf }) => ({ tier: r.tier, perf }))),
		retailers: getValueRetailers(db, category)
	};
}
