import type { DB, ProductRow } from '../db';
import type { Retailer } from '../../types';
import { LATEST_CTE, notBundle } from './sql';
import type { CompareEntry, ComparePrice, SpecRow } from '../../models';

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
