import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { DB } from '../../src/lib/server/db';
import { openDatabase } from '../../src/lib/server/db';

const here = path.dirname(fileURLToPath(import.meta.url));
export const SCHEMA_PATH = path.resolve(here, '..', '..', '..', 'db', 'schema.sql');
export const DATA_DIR = path.resolve(here, '..', '..', '..', 'data');

const MONTHS: Record<string, number> = {
	January: 1,
	February: 2,
	March: 3,
	April: 4,
	May: 5,
	June: 6,
	July: 7,
	August: 8,
	September: 9,
	October: 10,
	November: 11,
	December: 12
};

export function parseDateFromFilename(filename: string): string {
	if (!filename.endsWith('.json')) return '';
	const stem = path.basename(filename, '.json');
	const parts = stem.split('_');
	if (parts.length < 3) return '';
	const dateStr = parts.slice(-3).join('_');
	const match = dateStr.match(/^(\d{1,2})_(\w+)_(\d{4})$/);
	if (!match) return '';
	const day = Number(match[1]);
	const month = MONTHS[match[2]];
	const year = Number(match[3]);
	if (!month || Number.isNaN(day) || Number.isNaN(year)) return '';
	return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export interface SeededDb {
	db: DB;
	file: string;
	close: () => void;
}

export function seedDatabase(file: string): DB {
	const db = openDatabase(file, { readonly: false, fileMustExist: false });
	const schema = fs.readFileSync(SCHEMA_PATH, 'utf-8');
	db.exec(schema);

	const files = fs
		.readdirSync(DATA_DIR)
		.filter((f) => f.endsWith('.json'))
		.sort();

	const insertTemplate = db.transaction(() => {
		const findProduct = db.prepare(
			'SELECT id FROM products WHERE category = ? AND brand = ? AND model = ?'
		);
		const insertProduct = db.prepare(
			`INSERT INTO products (category, brand, model, generation_tier, tracked)
			 VALUES (?, ?, ?, ?, 1)`
		);
		const findListing = db.prepare(
			'SELECT id, variant_name FROM retailer_listings WHERE retailer = ? AND listing_url = ?'
		);
		const insertListing = db.prepare(
			`INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status)
			 VALUES (?, ?, ?, ?, 'active')`
		);
		const backfillVariant = db.prepare(
			'UPDATE retailer_listings SET variant_name = ? WHERE id = ? AND variant_name IS NULL'
		);
		const findSnapshot = db.prepare(
			'SELECT id FROM price_snapshots WHERE retailer_listing_id = ? AND snapshot_date = ?'
		);
		const insertSnapshot = db.prepare(
			`INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
			 VALUES (?, ?, ?, ?, ?)`
		);

		for (const file of files) {
			const data = JSON.parse(
				fs.readFileSync(path.join(DATA_DIR, file), 'utf-8')
			) as {
				retailer: string;
				products: Array<{
					watchlist_model: string;
					watchlist_category: string;
					watchlist_brand: string;
					watchlist_gen_tier?: string;
					scraped_name?: string;
					price_aud: number | null;
					stock_status?: string;
					url?: string;
				}>;
			};
			const snapshotDate = parseDateFromFilename(file);
			if (!snapshotDate) continue;

			for (const p of data.products) {
				if (!p.url || p.price_aud === null || p.price_aud === undefined) continue;

				const product = findProduct.get(
					p.watchlist_category,
					p.watchlist_brand,
					p.watchlist_model
				) as { id: number } | undefined;
				let productId: number;
				if (product) {
					productId = product.id;
				} else {
					const info = insertProduct.run(
						p.watchlist_category,
						p.watchlist_brand,
						p.watchlist_model,
						p.watchlist_gen_tier ?? 'current'
					);
					productId = Number(info.lastInsertRowid);
				}

				const listing = findListing.get(data.retailer, p.url) as
					| { id: number; variant_name: string | null }
					| undefined;
				let listingId: number;
				if (listing) {
					listingId = listing.id;
					if (p.scraped_name) backfillVariant.run(p.scraped_name, listingId);
				} else {
					const info = insertListing.run(
						productId,
						data.retailer,
						p.scraped_name ?? null,
						p.url
					);
					listingId = Number(info.lastInsertRowid);
				}

				const snapshotExists = findSnapshot.get(listingId, snapshotDate);
				if (!snapshotExists) {
					insertSnapshot.run(
						listingId,
						snapshotDate,
						p.price_aud,
						p.stock_status ?? 'unknown',
						`${snapshotDate}T04:00:00.000Z`
					);
				}
			}
		}
	});

	insertTemplate();
	return db;
}

export function createSeededDb(): SeededDb {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-'));
	const file = path.join(dir, 'test.db');
	const db = seedDatabase(file);
	return {
		db,
		file,
		close: () => {
			db.close();
			fs.rmSync(dir, { recursive: true, force: true });
		}
	};
}