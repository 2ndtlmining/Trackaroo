// Seeds the deterministic E2E database used by the Playwright dev server.
// Runs before `vite dev` via webServer.command so the server never polls
// against a missing DB (globalSetup runs too late for that).
import process from 'node:process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Database from 'better-sqlite3';

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, '..');
const SCHEMA_PATH = path.resolve(webRoot, '..', 'db', 'schema.sql');
const DATA_DIR = path.resolve(webRoot, '..', 'data');
const DB_PATH = path.join(here, 'e2e.db');

const MONTHS = {
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

function parseDateFromFilename(filename) {
	if (!filename.endsWith('.json')) return '';
	const stem = path.basename(filename, '.json');
	const parts = stem.split('_');
	if (parts.length < 3) return '';
	const match = parts.slice(-3).join('_').match(/^(\d{1,2})_(\w+)_(\d{4})$/);
	if (!match) return '';
	const day = Number(match[1]);
	const month = MONTHS[match[2]];
	const year = Number(match[3]);
	if (!month || Number.isNaN(day) || Number.isNaN(year)) return '';
	return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export function seedE2eDb(dbPath = DB_PATH) {
	if (fs.existsSync(dbPath)) fs.rmSync(dbPath);
	const db = new Database(dbPath);
	db.pragma('busy_timeout = 5000');
	db.pragma('foreign_keys = ON');
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));

	const files = fs
		.readdirSync(DATA_DIR)
		.filter((f) => f.endsWith('.json'))
		.sort();

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

	const insertAll = db.transaction(() => {
		for (const file of files) {
			const data = JSON.parse(fs.readFileSync(path.join(DATA_DIR, file), 'utf-8'));
			const snapshotDate = parseDateFromFilename(file);
			if (!snapshotDate) continue;

			for (const p of data.products) {
				if (!p.url || p.price_aud === null || p.price_aud === undefined) continue;

				const product = findProduct.get(p.watchlist_category, p.watchlist_brand, p.watchlist_model);
				let productId;
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

				const listing = findListing.get(data.retailer, p.url);
				let listingId;
				if (listing) {
					listingId = listing.id;
					if (p.scraped_name) backfillVariant.run(p.scraped_name, listingId);
				} else {
					const info = insertListing.run(productId, data.retailer, p.scraped_name ?? null, p.url);
					listingId = Number(info.lastInsertRowid);
				}

				if (!findSnapshot.get(listingId, snapshotDate)) {
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

	insertAll();

	// Deterministic spec rows so the product page spec panel is testable:
	// product 1 (Core Ultra 5 245, CPU) and the first GPU product.
	const firstProduct = db.prepare('SELECT id FROM products LIMIT 1').get();
	const firstGpu = db
		.prepare("SELECT id FROM products WHERE category = 'gpu' ORDER BY id LIMIT 1")
		.get();
	const insertSpec = db.prepare(
		`INSERT INTO specs (product_id, source, source_record_key, category, architecture, generation,
			launch_date, vram_gb, memory_bus_width_bit, memory_type, tdp_watts, core_count,
			thread_count, base_clock_mhz, boost_clock_mhz, socket, cache_l3_mb,
			gpu_die, bus_interface, memory_bandwidth_gbps, memory_clock_mhz, process_nm, foundry,
			codename, l1_cache_kb, l2_cache_mb, memory_speed_mhz, memory_channels, memory_types,
			integrated_graphics, raw_json, last_synced_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
			?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
	);
	if (firstProduct) {
		insertSpec.run(
			firstProduct.id,
			'intel-processors-csv',
			'Core Ultra 5 245',
			'cpu',
			'Arrow Lake',
			'Core Ultra 200S',
			'2025-12-04',
			null,
			null,
			null,
			45,
			10,
			10,
			2500,
			4800,
			'LGA1851',
			24,
			null,
			null,
			null,
			null,
			3,
			null,
			'Arrow Lake',
			null,
			null,
			6400,
			2,
			'Up to DDR5 6400 MT/s',
			'Intel Graphics',
			'{}',
			'2026-08-15T00:00:00Z'
		);
	}
	if (firstGpu) {
		insertSpec.run(
			firstGpu.id,
			'rightnow-gpu-db',
			'GeForce RTX 5060 Ti',
			'gpu',
			'Blackwell',
			'RTX 50',
			'2025-04-16',
			16,
			128,
			'GDDR7',
			180,
			4608,
			null,
			null,
			null,
			null,
			null,
			'GB203',
			'PCIe 5.0 x16',
			448,
			1750,
			5,
			'TSMC',
			null,
			null,
			48,
			null,
			null,
			null,
			null,
			'{}',
			'2026-08-15T00:00:00Z'
		);
	}

	db.close();
	return dbPath;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const created = seedE2eDb();
	// eslint-disable-next-line no-console
	console.log(`[e2e] seeded ${created}`);
}