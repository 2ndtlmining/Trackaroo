// @vitest-environment node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { openDatabase } from '../src/lib/server/db';
import { SCHEMA_PATH } from './helpers/seed';

let dir: string;

beforeEach(() => {
	dir = fs.mkdtempSync(path.join(os.tmpdir(), 'healthz-'));
	vi.resetModules(); // getDb() caches its connection per module instance
});

afterEach(async () => {
	try {
		(await import('../src/lib/server/db')).getDb().close();
	} catch {
		// never opened
	}
	delete process.env.TRACKAROO_VERSION;
	delete process.env.TRACKAROO_DB;
	fs.rmSync(dir, { recursive: true, force: true });
});

function seed(): string {
	const file = path.join(dir, 't.db');
	const db = openDatabase(file, { readonly: false, fileMustExist: false });
	db.exec(fs.readFileSync(SCHEMA_PATH, 'utf-8'));
	db.exec(`INSERT INTO active_retailers (retailer, position) VALUES ('scorptec', 0), ('umart', 1);
		INSERT INTO products (category, brand, model, tracked) VALUES ('cpu', 'AMD', 'Ryzen 5 5600', 1);
		INSERT INTO retailer_listings (product_id, retailer, listing_url, status) VALUES (1, 'scorptec', 'https://x/1', 'active');
		INSERT INTO price_snapshots (retailer_listing_id, snapshot_date, price_aud, stock_status) VALUES (1, '2026-09-28', 199, 'in_stock');`);
	db.close();
	return file;
}

describe('/healthz (#9)', () => {
	it('reports ok, the version and every active retailer', async () => {
		process.env.TRACKAROO_DB = seed();
		process.env.TRACKAROO_VERSION = 'abc1234';
		const { GET } = await import('../src/routes/healthz/+server');

		const res = GET();

		expect(res.status).toBe(200);
		expect(res.headers.get('cache-control')).toBe('no-store');
		const body = await res.json();
		expect(body).toMatchObject({ ok: true, version: 'abc1234', release: __APP_RELEASE__ });
		expect(body.retailers.map((r: { retailer: string; latestSnapshotDate: string | null }) => [r.retailer, r.latestSnapshotDate])).toEqual([
			['scorptec', '2026-09-28'],
			['umart', null]
		]);
	});

	it('says dev when no version was baked in', async () => {
		process.env.TRACKAROO_DB = seed();
		const { GET } = await import('../src/routes/healthz/+server');
		expect((await GET().json()).version).toBe('dev');
	});

	it('returns 503 when the database cannot be opened', async () => {
		process.env.TRACKAROO_DB = path.join(dir, 'missing.db');
		const { GET } = await import('../src/routes/healthz/+server');

		const res = GET();

		expect(res.status).toBe(503);
		expect((await res.json()).ok).toBe(false);
	});
});
