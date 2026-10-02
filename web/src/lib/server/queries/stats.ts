import { statSync } from 'node:fs';
import type { DB } from '../db';
import { dailyCheapestInStock } from './sql';
import type { HeaderStats, ProductStats } from '../../models';

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
