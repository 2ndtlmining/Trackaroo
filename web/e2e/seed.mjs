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
// Overridable like the backend's TRACKAROO_DATA_DIR (useful for CI / testing
// the synthetic fallback); defaults to the live scraped data directory.
const DATA_DIR = process.env.TRACKAROO_DATA_DIR
	? path.resolve(process.env.TRACKAROO_DATA_DIR)
	: path.resolve(webRoot, '..', 'data');
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

// Deterministic synthetic snapshot fixture — used ONLY when data/ has no JSON
// files (fresh clone / CI), so the e2e suite is runnable without a prior
// scrape. Mirrors the real scrape-file layout (retailer x category x date)
// and pins the same invariants the specs rely on: product id 1 is the Intel
// Core Ultra 5 245 (specs seeded below), the first GPU is the GeForce RTX
// 5060 Ti, all three brands and both retailers are present, there is a
// current-2 tier row, and listings carry price history for sparklines,
// movers, and the 90-day-low chips.
function buildSyntheticSources() {
	const dates = ['18_August_2026', '19_August_2026', '20_August_2026'];
	// model -> [category, brand, gen_tier]
	const defs = {
		'Core Ultra 5 245': ['cpu', 'Intel', 'current'],
		'Ryzen 5 5600': ['cpu', 'AMD', 'current-2'],
		'Ryzen 5 7600': ['cpu', 'AMD', 'current-1'],
		'Ryzen 9 9900X': ['cpu', 'AMD', 'current'],
		'GeForce RTX 5060 Ti': ['gpu', 'NVIDIA', 'current'],
		'GeForce RTX 5060': ['gpu', 'NVIDIA', 'current'],
		'Arc B580': ['gpu', 'Intel', 'current'],
		'Radeon RX 7800 XT': ['gpu', 'AMD', 'current-1']
	};
	// [model, retailer, scraped_name, url, prices per date (dates order)]
	const listings = [
		['Core Ultra 5 245', 'pccg', 'Intel Core Ultra 5 245 Boxed CPU', '/p/245-pccg', [489, 479, 459]],
		['Core Ultra 5 245', 'scorptec', 'Intel Core Ultra 5 245 Desktop Processor', '/p/245-sct', [469, 469, 469]],
		['Ryzen 5 5600', 'pccg', 'AMD Ryzen 5 5600 Processor', '/p/5600-pccg', [195, 195, 195]],
		['Ryzen 5 5600', 'scorptec', 'AMD Ryzen 5 5600', '/p/5600-sct', [189, 189, 189]],
		['Ryzen 5 7600', 'scorptec', 'AMD Ryzen 5 7600', '/p/7600-sct', [339, 339, 339]],
		['Ryzen 9 9900X', 'scorptec', 'AMD Ryzen 9 9900X', '/p/9900x-sct', [749, 749, 799]],
		['GeForce RTX 5060 Ti', 'pccg', 'ASUS GeForce RTX 5060 Ti TUF Gaming 16GB', '/p/5060ti-asus-pccg', [759, 759, 749]],
		['GeForce RTX 5060 Ti', 'scorptec', 'ASUS Dual GeForce RTX 5060 Ti 16GB', '/p/5060ti-asus-sct', [749, 719, 699]],
		['GeForce RTX 5060 Ti', 'scorptec', 'MSI Ventus GeForce RTX 5060 Ti 16GB', '/p/5060ti-msi-sct', [739, 739, 729]],
		['GeForce RTX 5060 Ti', 'scorptec', 'Gigabyte Windforce GeForce RTX 5060 Ti 16GB', '/p/5060ti-giga-sct', [729, 729, 729]],
		['GeForce RTX 5060', 'pccg', 'MSI GeForce RTX 5060 8GB', '/p/5060-msi-pccg', [559, 559, 559]],
		['GeForce RTX 5060', 'scorptec', 'Gigabyte GeForce RTX 5060 8GB', '/p/5060-giga-sct', [549, 549, 549]],
		['Arc B580', 'pccg', 'ASRock Intel Arc B580 12GB', '/p/b580-pccg', [429, 429, 429]],
		['Radeon RX 7800 XT', 'scorptec', 'Sapphire Pulse Radeon RX 7800 XT 16GB', '/p/7800xt-sct', [649, 649, 649]]
	];

	// Group listings into per (category x retailer x date) source files.
	const perKey = new Map();
	for (const [model, retailer, scrapedName, url, prices] of listings) {
		const [category, brand, gen] = defs[model];
		for (let d = 0; d < dates.length; d += 1) {
			const key = `${category}_${retailer}_${dates[d]}`;
			if (!perKey.has(key)) perKey.set(key, { products: [] });
			perKey.get(key).products.push({
				watchlist_model: model,
				watchlist_category: category,
				watchlist_brand: brand,
				watchlist_gen_tier: gen,
				retailer,
				scraped_name: scrapedName,
				price_aud: prices[d],
				stock_status: 'in_stock',
				url
			});
		}
	}

	// Deterministic processing order: cpu before gpu, pccg before scorptec, so
	// Core Ultra 5 245 becomes product id 1 and the RTX 5060 Ti the first GPU.
	const cpuModels = ['Core Ultra 5 245', 'Ryzen 5 5600', 'Ryzen 5 7600', 'Ryzen 9 9900X'];
	const gpuModels = ['GeForce RTX 5060 Ti', 'GeForce RTX 5060', 'Arc B580', 'Radeon RX 7800 XT'];
	const modelOrder = new Map([...cpuModels, ...gpuModels].map((m, i) => [m, i]));

	const names = [...perKey.keys()].sort((a, b) => {
		const [catA, retA] = a.split('_');
		const [catB, retB] = b.split('_');
		if (catA !== catB) return catA === 'cpu' ? -1 : 1;
		if (retA !== retB) return retA === 'pccg' ? -1 : 1;
		return dates.indexOf(a.split('_').slice(2).join('_')) - dates.indexOf(b.split('_').slice(2).join('_'));
	});

	return names.map((name) => {
		const [category, retailer] = name.split('_');
		const products = [...perKey.get(name).products].sort(
			(a, b) => modelOrder.get(a.watchlist_model) - modelOrder.get(b.watchlist_model)
		);
		return {
			name: `${name}.json`,
			data: {
				retailer,
				scrape_date: name.split('_').slice(2).join('_'),
				category,
				total_watchlist: products.length,
				matched: products.length,
				unmatched_count: 0,
				unmatched_models: [],
				products
			}
		};
	});
}

function loadSources() {
	const dataFiles = fs.existsSync(DATA_DIR)
		? fs.readdirSync(DATA_DIR)
				.filter((f) => f.endsWith('.json'))
				.sort()
		: [];
	if (dataFiles.length > 0) {
		return dataFiles.map((name) => ({
			name,
			data: JSON.parse(fs.readFileSync(path.join(DATA_DIR, name), 'utf-8'))
		}));
	}
	return buildSyntheticSources();
}

export function seedE2eDb(dbPath = DB_PATH) {
	if (fs.existsSync(dbPath)) fs.rmSync(dbPath);
	const db = new Database(dbPath);
	db.pragma('busy_timeout = 5000');
	db.pragma('foreign_keys = ON');
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));

	const sources = loadSources();

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
		for (const source of sources) {
			const data = source.data;
			const snapshotDate = parseDateFromFilename(source.name);
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