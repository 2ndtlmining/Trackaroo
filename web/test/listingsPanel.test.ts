import { describe, expect, it } from 'vitest';
import type { ListingRow, SnapshotRow } from '../src/lib/server/db';
import type { Series } from '../src/lib/server/repos';
import { priceRange, toListingDisplays } from '../src/lib/listingsPanel';

function snapshot(date: string, price: number, stock: string): SnapshotRow {
	return {
		id: 1,
		retailer_listing_id: 1,
		snapshot_date: date,
		price_aud: price,
		stock_status: stock as SnapshotRow['stock_status'],
		scraped_at: `${date}T04:00:00.000Z`
	};
}

function series(
	id: number,
	variant: string | null,
	points: SnapshotRow[],
	status: ListingRow['status'] = 'active'
): Series {
	const listing: ListingRow = {
		id,
		product_id: 1,
		retailer: 'scorptec',
		variant_name: variant,
		retailer_sku: null,
		listing_url: `https://example.com/${id}`,
		status,
		first_seen_at: '2026-08-09T04:00:00.000Z',
		last_seen_at: '2026-08-17T04:00:00.000Z',
		last_snapshot_at: '2026-08-17T04:00:00.000Z'
	};
	return { listing, points };
}

const GPU_PRODUCT_BRAND = 'NVIDIA';

const base = [
	series(1, 'MSI GeForce RTX 5060 Ventus 2X OC 8GB', [
		snapshot('2026-08-16', 619, 'in_stock'),
		snapshot('2026-08-17', 619, 'in_stock')
	]),
	series(2, 'Gigabyte GeForce RTX 5060 Windforce OC 8GB', [
		snapshot('2026-08-17', 649, 'in_stock')
	]),
	series(3, 'MSI GeForce RTX 5060 Shadow 2X OC 8GB', [
		snapshot('2026-08-17', 635, 'out_of_stock')
	]),
	series(4, 'ASUS Dual GeForce RTX 5060 8GB OC Edition', [
		snapshot('2026-08-17', 659, 'in_stock')
	]),
	series(5, 'ZOTAC Gaming GeForce RTX 5060 Twin Edge OC 8GB', [
		snapshot('2026-08-17', 699, 'in_stock')
	])
];

describe('toListingDisplays', () => {
	it('derives the brand from the variant first token and marks in-stock', () => {
		const displays = toListingDisplays(base, GPU_PRODUCT_BRAND, new Set());
		expect(displays[0].brand).toBe('MSI');
		expect(displays[1].brand).toBe('Gigabyte');
		expect(displays[4].brand).toBe('ZOTAC');
		expect(displays[0].inStock).toBe(true);
		expect(displays[2].inStock).toBe(false);
	});

	it('falls back to the product brand for non-brand variant prefixes', () => {
		const cpuLike = [
			series(9, 'Ryzen 5 7600, Tray, 65W', [snapshot('2026-08-17', 299, 'in_stock')])
		];
		const displays = toListingDisplays(cpuLike, 'AMD', new Set());
		expect(displays[0].brand).toBe('AMD');
	});

	it('carries the selected flag for toggled listing ids', () => {
		const displays = toListingDisplays(base, GPU_PRODUCT_BRAND, new Set([2]));
		expect(displays[0].selected).toBe(false);
		expect(displays[1].selected).toBe(true);
	});

	it('exposes latest price and date range', () => {
		const displays = toListingDisplays(base, GPU_PRODUCT_BRAND, new Set());
		expect(displays[0].latestPrice).toBe(619);
		expect(displays[0].firstSeen).toBe('2026-08-16');
		expect(displays[0].lastSeen).toBe('2026-08-17');
	});

	it('flags delisted listings and forces inStock false despite a stale in_stock snapshot', () => {
		const delisted = [
			series(10, 'XFX Radeon RX 7900XT', [snapshot('2026-08-10', 1049, 'in_stock')], 'delisted'),
			series(11, 'MSI GeForce RTX 5060 Ventus 2X OC 8GB', [snapshot('2026-08-17', 619, 'in_stock')])
		];
		const displays = toListingDisplays(delisted, GPU_PRODUCT_BRAND, new Set());
		expect(displays[0].delisted).toBe(true);
		expect(displays[0].inStock).toBe(false);
		expect(displays[0].latestStock).toBe('in_stock');
		expect(displays[1].delisted).toBe(false);
		expect(displays[1].inStock).toBe(true);
	});
});

describe('priceRange', () => {
	it('returns min/max over priced listings and nulls for unpriced ones', () => {
		const displays = toListingDisplays(base, GPU_PRODUCT_BRAND, new Set());
		expect(priceRange([displays[0], displays[1], displays[3]])).toEqual({ min: 619, max: 659 });
		expect(priceRange([displays[0]])).toEqual({ min: 619, max: 619 });
		const unpriced = { ...displays[0], latestPrice: null };
		expect(priceRange([unpriced])).toEqual({ min: null, max: null });
	});

	it('skips delisted listings so their stale price never skews the range', () => {
		const delisted = toListingDisplays(
			[series(10, 'XFX Radeon RX 7900XT', [snapshot('2026-08-10', 1049, 'in_stock')], 'delisted')],
			GPU_PRODUCT_BRAND,
			new Set()
		);
		expect(priceRange(delisted)).toEqual({ min: null, max: null });
		const mixed = [
			...toListingDisplays(
				[series(11, 'MSI GeForce RTX 5060 Ventus 2X OC 8GB', [snapshot('2026-08-17', 619, 'in_stock')])],
				GPU_PRODUCT_BRAND,
				new Set()
			),
			...delisted
		];
		expect(priceRange(mixed)).toEqual({ min: 619, max: 619 });
	});
});

describe('stale listings (#4)', () => {
	it('a status=stale listing is not in stock even if its last snapshot said so', () => {
		const s = series(9, 'ASUS TUF RTX 5090', [snapshot('2026-08-20', 7499, 'in_stock')], 'stale');
		const [d] = toListingDisplays([s], 'NVIDIA', new Set());
		expect(d.stale).toBe(true);
		expect(d.inStock).toBe(false);
	});

	it('an active listing unseen for more than 7 days before its retailer latest is stale', () => {
		const s = series(9, 'ASUS TUF RTX 5090', [snapshot('2026-08-20', 7499, 'in_stock')]);
		const [d] = toListingDisplays([s], 'NVIDIA', new Set(), { scorptec: '2026-09-28' });
		expect(d.stale).toBe(true);
		expect(d.inStock).toBe(false);
	});

	it('a listing seen within the window stays buyable', () => {
		const s = series(9, 'ASUS TUF RTX 5090', [snapshot('2026-09-25', 8999, 'in_stock')]);
		const [d] = toListingDisplays([s], 'NVIDIA', new Set(), { scorptec: '2026-09-28' });
		expect(d.stale).toBe(false);
		expect(d.inStock).toBe(true);
	});

	it('priceRange ignores stale listings', () => {
		const ghost = series(1, 'ghost', [snapshot('2026-08-20', 7499, 'in_stock')], 'stale');
		const live = series(2, 'live', [snapshot('2026-09-28', 8999, 'in_stock')]);
		expect(priceRange(toListingDisplays([ghost, live], 'NVIDIA', new Set()))).toEqual({ min: 8999, max: 8999 });
	});
});