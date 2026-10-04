// @vitest-environment node
import fs from 'node:fs';
import { beforeEach, describe, expect, it } from 'vitest';
import { openDatabase, type DB } from '../src/lib/server/db';
import { _resetMemo } from '../src/lib/server/cache';
import { getMatchup, getValueRows } from '../src/lib/server/repos';
import { SCHEMA_PATH } from './helpers/seed';

// Perf scores come from db/perf_index.json:
// 5060 Ti 16GB 35/35, 5060 Ti 8GB 35/25, RX 9060 XT 16GB 33/33,
// RX 9060 XT 8GB 32/30, Arc B580 12GB 26/25.
describe('getMatchup (#60)', () => {
	let db: DB;
	beforeEach(() => {
		_resetMemo();
		db = openDatabase(':memory:', { readonly: false, fileMustExist: false });
		db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
		db.exec(`INSERT INTO active_retailers (retailer, position) VALUES ('scorptec', 0);
			INSERT INTO products (id, category, brand, model, vram_gb, generation_tier, tracked) VALUES
				(1, 'gpu', 'NVIDIA', 'GeForce RTX 5060 Ti', 16, 'current', 1),
				(2, 'gpu', 'NVIDIA', 'GeForce RTX 5060 Ti 8GB', 8, 'current', 1),
				(3, 'gpu', 'AMD', 'Radeon RX 9060 XT', 16, 'current', 1),
				(4, 'gpu', 'Intel', 'Arc B580', 12, 'current', 1),
				(5, 'gpu', 'AMD', 'Radeon RX 9060 XT 8GB', 8, 'current', 1),
				(6, 'gpu', 'AMD', 'Radeon RX 7600', 8, 'current', 0);
			INSERT INTO retailer_listings (id, product_id, retailer, variant_name, listing_url, status) VALUES
				(1, 1, 'scorptec', 'A', 'https://x/1', 'active'),
				(2, 2, 'scorptec', 'B', 'https://x/2', 'active'),
				(3, 3, 'scorptec', 'C', 'https://x/3', 'active'),
				(4, 4, 'scorptec', 'D', 'https://x/4', 'active'),
				(5, 5, 'scorptec', 'E', 'https://x/5', 'active'),
				(6, 6, 'scorptec', 'F', 'https://x/6', 'active');
			INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES
				(1, '2026-10-03', 600, 'in_stock'),
				(2, '2026-10-03', 520, 'in_stock'),
				(3, '2026-10-03', 650, 'in_stock'),
				(4, '2026-10-03', 400, 'in_stock'),
				(5, '2026-10-03', 299, 'out_of_stock'),
				(6, '2026-10-03', 199, 'in_stock');`);
	});

	it('returns brand on value rows', () => {
		expect(getValueRows(db, 'gpu').find((r) => r.id === 4)?.brand).toBe('Intel');
	});

	it('pairs the 5060 Ti 16GB with the RX 9060 XT 16GB, with display names and Perf/A$1k', () => {
		const m = getMatchup(db, 1);
		expect(m).not.toBeNull();
		expect(m!.category).toBe('gpu');
		expect(m!.metric).toBe('gpu_raster_1440p');
		expect(m!.product).toEqual({ id: 1, name: 'GeForce RTX 5060 Ti 16GB', price: 600, perfPerKilo: (35 / 600) * 1000 });
		expect(m!.rival).toEqual({ id: 3, name: 'Radeon RX 9060 XT 16GB', price: 650, perfPerKilo: (33 / 650) * 1000 });
		expect(m!.lines).toEqual([
			{ metric: 'gpu_raster_1440p', direction: 'cheaper', pct: 13 },
			{ metric: 'gpu_rt_1440p', direction: 'cheaper', pct: 13 }
		]);
	});

	it('shows raster and RT pointing different ways for the 8GB card', () => {
		expect(getMatchup(db, 2)!.lines).toEqual([
			{ metric: 'gpu_raster_1440p', direction: 'cheaper', pct: 25 },
			{ metric: 'gpu_rt_1440p', direction: 'dearer', pct: 6 }
		]);
	});

	it('lets VRAM beat the cheaper card on an exact gap tie', () => {
		// Both NVIDIA cards score 35 against 33; the 8GB one is cheaper.
		expect(getMatchup(db, 3)!.rival.id).toBe(1);
	});

	it('is null for an Intel GPU, an out-of-stock product, an untracked one and an unknown id', () => {
		expect(getMatchup(db, 4)).toBeNull();
		expect(getMatchup(db, 5)).toBeNull();
		expect(getMatchup(db, 6)).toBeNull();
		expect(getMatchup(db, 999)).toBeNull();
	});
});
