// Seeds the deterministic E2E database used by the Playwright dev server.
// Runs before `vite dev` via webServer.command so the server never polls
// against a missing DB (globalSetup runs too late for that).
import process from 'node:process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Database from 'better-sqlite3';
import { seedGenerations } from './generations.mjs';

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
export function buildSyntheticSources() {
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
	// [model, retailer, scraped_name, url, prices per date (dates order), optional
	// stock statuses per date (dates order) — defaults to all 'in_stock' when omitted]
	const listings = [
		['Core Ultra 5 245', 'pccg', 'Intel Core Ultra 5 245 Boxed CPU', '/p/245-pccg', [489, 479, 459]],
		['Core Ultra 5 245', 'scorptec', 'Intel Core Ultra 5 245 Desktop Processor', '/p/245-sct', [469, 469, 469]],
		['Ryzen 5 5600', 'pccg', 'AMD Ryzen 5 5600 Processor', '/p/5600-pccg', [195, 195, 195]],
		['Ryzen 5 5600', 'scorptec', 'AMD Ryzen 5 5600', '/p/5600-sct', [189, 189, 189]],
		['Ryzen 5 7600', 'scorptec', 'AMD Ryzen 5 7600', '/p/7600-sct', [339, 339, 339]],
		// Flat (#22 Task 5): the CPU section must have no rise, so the homepage's
		// empty-column line is testable. The only rising fixture is the GPU riser.
		['Ryzen 9 9900X', 'scorptec', 'AMD Ryzen 9 9900X', '/p/9900x-sct', [799, 799, 799]],
		// RTX 5060 Ti carries 12 listings on purpose (10 in-stock + 2 out-of-stock,
		// across both retailers and several AIB brands) so the product page's
		// offer-list expander, in-stock filter, and facet chips are all
		// exercisable in E2E without depending on the live scrape data/ directory.
		['GeForce RTX 5060 Ti', 'pccg', 'ASUS GeForce RTX 5060 Ti TUF Gaming 16GB', '/p/5060ti-asus-pccg', [759, 759, 749]],
		['GeForce RTX 5060 Ti', 'scorptec', 'ASUS Dual GeForce RTX 5060 Ti 16GB', '/p/5060ti-asus-sct', [749, 719, 699]],
		['GeForce RTX 5060 Ti', 'scorptec', 'MSI Ventus GeForce RTX 5060 Ti 16GB', '/p/5060ti-msi-sct', [739, 739, 729]],
		['GeForce RTX 5060 Ti', 'scorptec', 'Gigabyte Windforce GeForce RTX 5060 Ti 16GB', '/p/5060ti-giga-sct', [729, 729, 729]],
		['GeForce RTX 5060 Ti', 'pccg', 'MSI GeForce RTX 5060 Ti Ventus 16GB', '/p/5060ti-msi-pccg', [745, 745, 735]],
		['GeForce RTX 5060 Ti', 'pccg', 'Gigabyte GeForce RTX 5060 Ti Windforce 16GB', '/p/5060ti-giga-pccg', [735, 735, 725]],
		['GeForce RTX 5060 Ti', 'pccg', 'Zotac GeForce RTX 5060 Ti Twin Edge 16GB', '/p/5060ti-zotac-pccg', [755, 755, 745]],
		['GeForce RTX 5060 Ti', 'scorptec', 'Zotac GeForce RTX 5060 Ti Twin Edge 16GB', '/p/5060ti-zotac-sct', [744, 744, 734]],
		['GeForce RTX 5060 Ti', 'scorptec', 'Palit GeForce RTX 5060 Ti Dual 16GB', '/p/5060ti-palit-sct', [734, 734, 724]],
		['GeForce RTX 5060 Ti', 'scorptec', 'Inno3D GeForce RTX 5060 Ti Twin X2 16GB', '/p/5060ti-inno3d-sct', [724, 724, 714]],
		[
			'GeForce RTX 5060 Ti',
			'pccg',
			'PNY GeForce RTX 5060 Ti OC 16GB',
			'/p/5060ti-pny-pccg',
			[765, 765, 755],
			['out_of_stock', 'out_of_stock', 'out_of_stock']
		],
		[
			'GeForce RTX 5060 Ti',
			'scorptec',
			'PNY GeForce RTX 5060 Ti OC 16GB',
			'/p/5060ti-pny-sct',
			[764, 764, 754],
			['out_of_stock', 'out_of_stock', 'out_of_stock']
		],
		['GeForce RTX 5060', 'pccg', 'MSI GeForce RTX 5060 8GB', '/p/5060-msi-pccg', [559, 559, 559]],
		['GeForce RTX 5060', 'scorptec', 'Gigabyte GeForce RTX 5060 8GB', '/p/5060-giga-sct', [549, 549, 549]],
		['Arc B580', 'pccg', 'ASRock Intel Arc B580 12GB', '/p/b580-pccg', [429, 429, 429]],
		['Radeon RX 7800 XT', 'scorptec', 'Sapphire Pulse Radeon RX 7800 XT 16GB', '/p/7800xt-sct', [649, 649, 649]]
	];

	// Group listings into per (category x retailer x date) source files.
	const perKey = new Map();
	for (const [model, retailer, scrapedName, url, prices, stockStatuses] of listings) {
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
				stock_status: stockStatuses ? stockStatuses[d] : 'in_stock',
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

// /value fixtures (#33). Deterministic whatever data/ holds, so the specs never
// depend on the scraped data.
//  1. vram_gb from db/watchlist.csv for every GPU that has none, as seed.py
//     does in a real DB. The performance index is keyed "<model> <vram>GB", so
//     without it only the two hand-set cards above resolve to an entry.
//  2. Five products whose model names are real index keys, with pinned prices
//     and stock, always created: two CPUs in stock, one CPU out of stock only
//     ("N without an in-stock price are not shown" has a member) and two 8 GB
//     GPUs in stock at A$299 and A$199 (best under A$400 on both seeds, so excluding 8 GB
//     cards always changes a budget card). If a scraped row for the same
//     product exists its listings are delisted, so the pinned listing is the
//     only price the value pages can see.
function seedValueFixtures(db) {
	const watchlist = fs.readFileSync(path.resolve(webRoot, '..', 'db', 'watchlist.csv'), 'utf-8');
	const setVram = db.prepare(
		"UPDATE products SET vram_gb = ? WHERE category = 'gpu' AND model = ? AND vram_gb IS NULL"
	);
	for (const line of watchlist.split(/\r?\n/)) {
		if (!line.trim() || line.startsWith('#')) continue;
		const [category, , model, spec] = line.split(',');
		const gb = /^(\d+)GB$/i.exec(spec ?? '');
		if (category === 'gpu' && gb) setVram.run(Number(gb[1]), model);
	}

	const latest = db.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots').get()?.d;
	if (!latest) return;
	const fixtures = [
		['cpu', 'AMD', 'Ryzen 7 9800X3D', null, 749, 'in_stock'],
		['cpu', 'AMD', 'Ryzen 5 9600X', null, 349, 'in_stock'],
		['cpu', 'Intel', 'Core Ultra 7 265K', null, 529, 'out_of_stock'],
		['gpu', 'AMD', 'Radeon RX 9060 XT 8GB', 8, 299, 'in_stock'],
		['gpu', 'AMD', 'Radeon RX 7600', 8, 199, 'in_stock']
	];
	for (const [category, brand, model, vram, price, stock] of fixtures) {
		const found = db
			.prepare(
				`SELECT id FROM products WHERE category = ? AND model = ?
				   AND (? IS NULL OR vram_gb = ?) ORDER BY id LIMIT 1`
			)
			.get(category, model, vram, vram);
		let productId;
		if (found) {
			productId = found.id;
			db.prepare("UPDATE retailer_listings SET status = 'delisted' WHERE product_id = ?").run(productId);
			db.prepare("UPDATE products SET tracked = 1, generation_tier = 'current' WHERE id = ?").run(productId);
		} else {
			productId = Number(
				db
					.prepare(
						`INSERT INTO products (category, brand, model, generation_tier, tracked, vram_gb)
						 VALUES (?, ?, ?, 'current', 1, ?)`
					)
					.run(category, brand, model, vram).lastInsertRowid
			);
		}
		const slug = `${model}-${vram ?? ''}`.toLowerCase().replace(/[^a-z0-9]+/g, '-');
		const listingId = Number(
			db
				.prepare(
					`INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status)
					 VALUES (?, 'scorptec', ?, ?, 'active')`
				)
				.run(productId, `${brand} ${model} Fixture`, `/p/e2e-value-${slug}`).lastInsertRowid
		);
		// Flat for three days: never a deal, a mover or a new low.
		for (const n of [2, 1, 0]) {
			const date = db.prepare('SELECT date(?, ?) AS d').get(latest, `-${n} days`).d;
			db.prepare(
				`INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
				 VALUES (?, ?, ?, ?, ?)`
			).run(listingId, date, price, stock, `${date}T04:00:00.000Z`);
		}
	}
}

export function seedE2eDb(dbPath = DB_PATH) {
	if (fs.existsSync(dbPath)) fs.rmSync(dbPath);
	const db = new Database(dbPath);
	db.pragma('busy_timeout = 5000');
	db.pragma('foreign_keys = ON');
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
	seedGenerations(db, webRoot);

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

	// Deterministic delisted listing for the product-detail panel: a stale
	// in-stock snapshot on a status='delisted' listing must render as a
	// "Delisted" badge, never as buyable. Attached to the RTX 5060 Ti, which
	// exists in both the synthetic fixture and the live scrape data.
	const delistedTarget = db
		.prepare("SELECT id FROM products WHERE category = 'gpu' AND model = 'GeForce RTX 5060 Ti' LIMIT 1")
		.get();
	if (delistedTarget) {
		const delistedInfo = db
			.prepare(
				`INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status)
				 VALUES (?, 'scorptec', 'XFX Delisted Demo 16GB', '/p/delisted-demo-sct', 'delisted')`
			)
			.run(delistedTarget.id);
		db.prepare(
			`INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
			 VALUES (?, '2026-08-10', 699, 'in_stock', '2026-08-10T04:00:00.000Z')`
		).run(Number(delistedInfo.lastInsertRowid));
	}

	// Deterministic /deals fixtures. The seed builds from the live data/
	// directory when it has files, so real scraped prices cannot be asserted
	// on. These products are synthetic and pinned:
	//
	//   E2E Deal Demo GPU  — today's price is 90% below its 30-day average and
	//     equal to its all-time low, so it must rank FIRST in the below-average
	//     section. It also clears the #6 floors (>=2%, >=$10) by a wide margin,
	//     so under the #6 dedup rule it is shown ONLY there, not in the
	//     at-a-new-low section too. Real hardware does not swing 90% in a
	//     month, which is what makes the ordering assertion safe against live
	//     data.
	//   E2E Thin History GPU — 40% below its 2-day average, but only 2 days of
	//     history, so MIN_HISTORY_POINTS must exclude it from both sections.
	//   E2E New Low GPU (#6) — today's price is a new all-time low, earned by
	//     a >=3% drop from within the window, but the 30-day average sits close
	//     enough that it clears NEITHER #6 floor (2%, $10). It therefore shows
	//     up ONLY in the at-a-new-low section, giving that section a fixture
	//     that is never also a below-average deal.
	//
	// Snapshots are anchored to the DB's own latest date so the fixtures are
	// always "today" regardless of which scrape files were loaded.
	const latestRow = db.prepare('SELECT MAX(snapshot_date) AS d FROM price_snapshots').get();
	if (latestRow && latestRow.d) {
		const dayBefore = (n) => db.prepare('SELECT date(?, ?) AS d').get(latestRow.d, `-${n} days`).d;

		const addDealFixture = (model, url, history) => {
			const productInfo = db
				.prepare(
					`INSERT INTO products (category, brand, model, generation_tier, tracked)
					 VALUES ('gpu', 'NVIDIA', ?, 'current', 1)`
				)
				.run(model);
			const listingInfo = db
				.prepare(
					`INSERT INTO retailer_listings (product_id, retailer, variant_name, listing_url, status)
					 VALUES (?, 'scorptec', ?, ?, 'active')`
				)
				.run(Number(productInfo.lastInsertRowid), `${model} Variant`, url);
			const listingId = Number(listingInfo.lastInsertRowid);
			for (const [daysAgo, price] of history) {
				const date = dayBefore(daysAgo);
				db.prepare(
					`INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status, scraped_at)
					 VALUES (?, ?, ?, 'in_stock', ?)`
				).run(listingId, date, price, `${date}T04:00:00.000Z`);
			}
		};

		// [daysAgo, price] — day 0 is the latest snapshot date.
		addDealFixture('E2E Deal Demo GPU', '/p/e2e-deal-demo', [
			[4, 1000],
			[3, 1000],
			[2, 1000],
			[1, 1000],
			[0, 100]
		]);
		addDealFixture('E2E Thin History GPU', '/p/e2e-thin-history', [
			[1, 1000],
			[0, 600]
		]);
		// avg30 = (520+510+505+502+500)/5 = 507.4 -- depth ~1.46%, saving ~$7.40,
		// both under the #6 floors -- while windowHigh (520) sits >=3% above
		// today's price (500 == allTimeLow), so it earns the new-low badge.
		addDealFixture('E2E New Low GPU', '/p/e2e-new-low', [
			[4, 520],
			[3, 510],
			[2, 505],
			[1, 502],
			[0, 500]
		]);
		// E2E Riser GPU (#22 Task 5): +12% over its last 5 days, so the GPU
		// section always has a "Biggest rises" column whatever data/ holds (the
		// synthetic GPUs only fall). Above its average, so never a deal.
		addDealFixture('E2E Riser GPU', '/p/e2e-riser', [
			[4, 500],
			[3, 500],
			[2, 500],
			[1, 500],
			[0, 560]
		]);
		// E2E Sale Window GPU (Task 5): a flat price with one extra day inside
		// the most recent EOFY sale (20 June), so the chart's date range covers a
		// sale event whatever data/ holds. Flat, so it is never a deal or a mover.
		const latestYear = Number(latestRow.d.slice(0, 4));
		const eofyYear = latestRow.d >= `${latestYear}-07-01` ? latestYear : latestYear - 1;
		const eofyDaysAgo = db
			.prepare('SELECT CAST(julianday(?) - julianday(?) AS INTEGER) AS n')
			.get(latestRow.d, `${eofyYear}-06-20`).n;
		addDealFixture('E2E Sale Window GPU', '/p/e2e-sale-window', [
			[eofyDaysAgo, 800],
			[2, 800],
			[1, 800],
			[0, 800]
		]);
	}

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

	// A second GPU with a smaller VRAM so /compare has a best value to mark (#26).
	const smallGpu = db
		.prepare("SELECT id FROM products WHERE category = 'gpu' AND model = 'GeForce RTX 5060'")
		.get();
	if (smallGpu) {
		db.prepare(
			`INSERT INTO specs (product_id, source, source_record_key, category, vram_gb, raw_json, last_synced_at)
			 VALUES (?, 'rightnow-gpu-db', 'GeForce RTX 5060', 'gpu', 8, '{}', '2026-08-15T00:00:00Z')`
		).run(smallGpu.id);
	}

	// US launch MSRPs for the vs-MSRP cues (Task 3, #32). Only on two pinned
	// deal fixtures whose prices never change (never on real products, whose
	// prices come from data/ and could land near 0%):
	// at the seeded 1.5 AUD/USD, MSRP in AUD = USD x 1.65, so
	//   E2E Deal Demo GPU  A$100 vs US$399 (A$658.35) -> 85% under
	//   E2E New Low GPU    A$500 vs US$279 (A$460.35) -> 9% over
	const msrpFixture = db.prepare(
		`INSERT INTO specs (product_id, source, source_record_key, category, launch_msrp_usd, raw_json, last_synced_at)
		 SELECT id, 'rightnow-gpu-db', model, 'gpu', ?, '{}', '2026-08-15T00:00:00Z'
		 FROM products WHERE category = 'gpu' AND model = ?`
	);
	msrpFixture.run(399, 'E2E Deal Demo GPU');
	msrpFixture.run(279, 'E2E New Low GPU');

	// Catalog columns and the never-listed toggle (#23), and a memory-size
	// sibling for the VRAM display label (Task 12). The watchlist fills vram_gb
	// and cores in real DBs; this seed builds products from snapshot JSON,
	// which does not carry them.
	db.prepare(
		"UPDATE products SET vram_gb = 16 WHERE category = 'gpu' AND model IN ('GeForce RTX 5060 Ti', 'E2E Deal Demo GPU')"
	).run();
	db.prepare("UPDATE products SET vram_gb = 8 WHERE category = 'gpu' AND model = 'GeForce RTX 5060'").run();
	db.prepare("UPDATE products SET cores = 10 WHERE category = 'cpu' AND model = 'Core Ultra 5 245'").run();
	db.prepare(
		`INSERT INTO products (category, brand, model, generation_tier, tracked, vram_gb)
		 VALUES ('gpu', 'NVIDIA', 'E2E Deal Demo GPU 8GB', 'current', 1, 8)`
	).run();
	seedValueFixtures(db);

	// The pipeline mirrors config.ACTIVE_RETAILERS into this table (R1). MWave is
	// declared active here with no rows on purpose: the health strip must list
	// it as "missing" in both the synthetic and the real-data seed.
	const activeRetailer = db.prepare(
		'INSERT INTO active_retailers (retailer, position) VALUES (?, ?)'
	);
	['scorptec', 'pccg', 'umart', 'mwave'].forEach((r, i) => activeRetailer.run(r, i));

	// ── Discovery fixtures (#16) ─────────────────────────────────────────
	// Deterministic rows so /discover renders in e2e regardless of data/.
	const today = (() => {
		const d = new Date();
		const p = (n) => String(n).padStart(2, '0');
		return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
	})();
	const part = db.prepare(
		`INSERT INTO discovered_parts (category, part_key, display_name, status, first_seen, last_seen, listing_count,
		   retailers, min_price, min_price_url, sample_titles, suggested_row)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
	);
	part.run('gpu', 'rtx 5050|8', 'GeForce RTX 5050 8GB', 'untracked', today, today, 6, 'pccg,scorptec,umart', 389,
		'https://example.com/5050', JSON.stringify(['MSI GeForce RTX 5050 Ventus 2X OC 8G']),
		'gpu,NVIDIA,GeForce RTX 5050,8GB,current');
	part.run('cpu', 'ryzen 5600gt', 'Ryzen 5 5600GT', 'untracked', '2026-08-09', today, 4, 'pccg,scorptec', 189,
		'https://example.com/5600gt', JSON.stringify(['AMD Ryzen 5 5600GT Processor']),
		'cpu,AMD,Ryzen 5 5600GT,?c,current-2');
	part.run('cpu', 'ultra 270k plus', 'Core Ultra 7 270K Plus', 'requested', today, today, 2, 'umart', 649,
		'https://example.com/270k', JSON.stringify(['Intel Core Ultra 7 270K Plus']),
		'cpu,Intel,Core Ultra 7 270K Plus,?c,current');
	part.run('gpu', 'rx 7600 xt|16', 'Radeon RX 7600 XT 16GB', 'ignored', '2026-09-20', today, 3, 'pccg', 499,
		'https://example.com/7600xt', JSON.stringify(['ASUS Dual RX 7600 XT 16GB']),
		'gpu,AMD,Radeon RX 7600 XT,16GB,current-1');
	db.prepare(
		`INSERT INTO discovery_runs (run_date, finished_at, catalogue_files, missing, unrecognised_count, unrecognised_samples)
		 VALUES (?, ?, 6, '[]', 1, ?)`
	).run(today, `${today}T04:41:00`, JSON.stringify(['Arctic MX-6 thermal paste']));
	const anyListing = db.prepare('SELECT id, product_id FROM retailer_listings LIMIT 1').get();
	if (anyListing) {
		db.prepare(`INSERT INTO discovery_conflicts VALUES (?, 'scorptec', ?, 'rx 9070 gre', ?, ?, ?)`).run(
			anyListing.id, anyListing.product_id, 'title names rx 9070 gre, product is rx 9070',
			'Sapphire Pulse RX 9070 GRE 12GB', today
		);
	}

	// Ready-to-retire fixture (#17): one pending suggestion for a seeded product.
	const retireProduct = db.prepare("SELECT id FROM products WHERE model = 'Ryzen 5 5600' ORDER BY id LIMIT 1").get();
	if (retireProduct) {
		db.prepare(
			`INSERT INTO retire_suggestions (product_id, first_flagged, last_seen, last_seen_retailer)
			 VALUES (?, ?, '2026-08-20', 'pccg')`
		).run(retireProduct.id, today);
	}

	// One cached AUD/USD rate so the MSRP cues have a value to show.
	db.prepare(`INSERT INTO fx_rates (rate_date, aud_per_usd, source, fetched_at) VALUES (?, 1.5, 'rba', ?)`).run(
		today, `${today}T00:00:00Z`
	);

	// OzBargain deals (#34) for E2E Deal Demo GPU, whose best in-stock price
	// today is A$100: one live deal below it, one live above it, and one that
	// expired today. Timestamps are relative to now so "live" and the 30-day
	// expired window always hold.
	const ozbAt = (hoursAgo) => new Date(Date.now() - hoursAgo * 3_600_000).toISOString();
	const ozb = db.prepare(
		`INSERT INTO ozb_deals (node_id, category, title, url, price_aud, retailer, votes_pos, votes_neg,
		   comment_count, posted_at, expired, product_id, first_seen_at, last_seen_at)
		 SELECT ?, 'gpu', ?, ?, ?, ?, ?, ?, 0, ?, ?, id, ?, ?
		 FROM products WHERE category = 'gpu' AND model = 'E2E Deal Demo GPU'`
	);
	for (const [node, title, price, retailer, pos, neg, hoursAgo, expired] of [
		[910001, 'E2E Deal Demo GPU $89 @ Amazon AU', 89, 'Amazon AU', 42, 1, 3, 0],
		[910002, 'E2E Deal Demo GPU $1,099 @ Mwave', 1099, 'Mwave', 5, 2, 26, 0],
		[910003, 'E2E Deal Demo GPU $79 @ eBay', 79, 'eBay', 12, 0, 120, 1]
	]) {
		const at = ozbAt(hoursAgo);
		ozb.run(node, title, `https://www.ozbargain.com.au/node/${node}`, price, retailer, pos, neg, at, expired, at,
			expired ? ozbAt(1) : at);
	}

	db.close();
	return dbPath;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const created = seedE2eDb();
	// eslint-disable-next-line no-console
	console.log(`[e2e] seeded ${created}`);
}