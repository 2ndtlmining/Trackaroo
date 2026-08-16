import { describe, expect, it } from 'vitest';
import type { ListingRow, SnapshotRow } from '../src/lib/server/db';
import type { Series } from '../src/lib/server/repos';
import { buildBrandGroups, priceRange, toListingDisplays } from '../src/lib/listingsPanel';

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

function series(id: number, variant: string | null, points: SnapshotRow[]): Series {
	const listing: ListingRow = {
		id,
		product_id: 1,
		retailer: 'scorptec',
		variant_name: variant,
		retailer_sku: null,
		listing_url: `https://example.com/${id}`,
		status: 'active',
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
});

describe('priceRange', () => {
	it('returns min/max over priced listings and nulls for unpriced ones', () => {
		const displays = toListingDisplays(base, GPU_PRODUCT_BRAND, new Set());
		expect(priceRange([displays[0], displays[1], displays[3]])).toEqual({ min: 619, max: 659 });
		expect(priceRange([displays[0]])).toEqual({ min: 619, max: 619 });
		const unpriced = { ...displays[0], latestPrice: null };
		expect(priceRange([unpriced])).toEqual({ min: null, max: null });
	});
});

describe('buildBrandGroups', () => {
	it('groups by derived brand with in-stock counts', () => {
		const groups = buildBrandGroups(base, GPU_PRODUCT_BRAND, { query: '', inStockOnly: false }, new Set());
		expect(groups.length).toBe(4); // MSI, Gigabyte, ASUS, ZOTAC
		const msi = groups.find((g) => g.brand === 'MSI')!;
		expect(msi.listings.length).toBe(2);
		expect(msi.inStockCount).toBe(1);
		expect(msi.minPrice).toBe(619);
		expect(msi.maxPrice).toBe(635);
	});

	it('sorts groups cheapest in-stock first', () => {
		const groups = buildBrandGroups(base, GPU_PRODUCT_BRAND, { query: '', inStockOnly: false }, new Set());
		const brands = groups.map((g) => g.brand);
		// MSI (619) -> Gigabyte (649) -> ASUS (659) -> ZOTAC (699)
		expect(brands).toEqual(['MSI', 'Gigabyte', 'ASUS', 'ZOTAC']);
	});

	it('filters by free-text query against the variant name', () => {
		const groups = buildBrandGroups(base, GPU_PRODUCT_BRAND, { query: 'ventus', inStockOnly: false }, new Set());
		expect(groups.length).toBe(1);
		expect(groups[0].brand).toBe('MSI');
		expect(groups[0].listings.length).toBe(1);
	});

	it('filters to in-stock only', () => {
		const groups = buildBrandGroups(base, GPU_PRODUCT_BRAND, { query: '', inStockOnly: true }, new Set());
		for (const g of groups) {
			for (const l of g.listings) {
				expect(l.inStock).toBe(true);
			}
		}
		expect(groups.flatMap((g) => g.listings).length).toBe(4);
	});

	it('hides groups with no matching listings', () => {
		const groups = buildBrandGroups(base, GPU_PRODUCT_BRAND, { query: 'does-not-exist', inStockOnly: false }, new Set());
		expect(groups.length).toBe(0);
	});
});