import { describe, expect, it } from 'vitest';
import type { ListingDisplay } from '../src/lib/offers';
import { offerTier, sortOffers } from '../src/lib/offers';
import { offer } from './helpers/offers';

describe('offerTier', () => {
	it('ranks in stock, then out of stock, then delisted', () => {
		expect(offerTier(offer())).toBe('in_stock');
		expect(offerTier(offer({ inStock: false, latestStock: 'out_of_stock' }))).toBe(
			'out_of_stock'
		);
		expect(offerTier(offer({ delisted: true, inStock: false }))).toBe('delisted');
	});
});

describe('sortOffers', () => {
	it('never places an out-of-stock offer above an in-stock one, even when cheaper', () => {
		const rows = sortOffers([
			offer({ listingId: 1, latestPrice: 999, inStock: false, latestStock: 'out_of_stock' }),
			offer({ listingId: 2, latestPrice: 1099 })
		]);
		expect(rows.map((r) => r.listingId)).toEqual([2, 1]);
	});

	it('sorts in-stock offers cheapest first', () => {
		const rows = sortOffers([
			offer({ listingId: 1, latestPrice: 1499 }),
			offer({ listingId: 2, latestPrice: 1099 }),
			offer({ listingId: 3, latestPrice: 1299 })
		]);
		expect(rows.map((r) => r.listingId)).toEqual([2, 3, 1]);
	});

	it('puts delisted offers last regardless of price', () => {
		const rows = sortOffers([
			offer({ listingId: 1, latestPrice: 1, delisted: true, inStock: false }),
			offer({ listingId: 2, latestPrice: 1499 })
		]);
		expect(rows.map((r) => r.listingId)).toEqual([2, 1]);
	});

	it('sorts null prices last within their tier', () => {
		const rows = sortOffers([
			offer({ listingId: 1, latestPrice: null, inStock: false, latestStock: 'unknown' }),
			offer({ listingId: 2, latestPrice: 1499, inStock: false, latestStock: 'out_of_stock' })
		]);
		expect(rows.map((r) => r.listingId)).toEqual([2, 1]);
	});

	it('does not mutate its input', () => {
		const input = [offer({ listingId: 1, latestPrice: 1499 }), offer({ listingId: 2, latestPrice: 1099 })];
		sortOffers(input);
		expect(input.map((r) => r.listingId)).toEqual([1, 2]);
	});
});

import { facetCounts } from '../src/lib/offers';
import { RETAILER_OPTIONS } from '../src/lib/filters';

describe('facetCounts', () => {
	it('counts offers per value, most common first', () => {
		const rows = [
			offer({ listingId: 1, retailer: 'scorptec' }),
			offer({ listingId: 2, retailer: 'pccg' }),
			offer({ listingId: 3, retailer: 'scorptec' })
		];
		expect(facetCounts(rows, 'retailer')).toEqual([
			{ value: 'scorptec', label: 'Scorptec', count: 2 },
			{ value: 'pccg', label: 'PCCG', count: 1 }
		]);
	});

	it('labels retailers from RETAILER_OPTIONS and falls back to the raw slug', () => {
		const known = RETAILER_OPTIONS[0];
		const rows = [offer({ retailer: known.value }), offer({ listingId: 2, retailer: 'newshop' })];
		const counts = facetCounts(rows, 'retailer');
		expect(counts.find((c) => c.value === known.value)?.label).toBe(known.label);
		expect(counts.find((c) => c.value === 'newshop')?.label).toBe('newshop');
	});

	it('uses the brand string as its own label', () => {
		const rows = [offer({ brand: 'ASUS' }), offer({ listingId: 2, brand: 'MSI' })];
		expect(facetCounts(rows, 'brand').map((c) => c.label)).toEqual(['ASUS', 'MSI']);
	});

	it('breaks count ties alphabetically so ordering is stable', () => {
		const rows = [offer({ brand: 'ZOTAC' }), offer({ listingId: 2, brand: 'ASUS' })];
		expect(facetCounts(rows, 'brand').map((c) => c.value)).toEqual(['ASUS', 'ZOTAC']);
	});

	it('returns one entry when every offer shares a value, so the caller can hide the row', () => {
		const rows = [offer({ brand: 'ASUS' }), offer({ listingId: 2, brand: 'ASUS' })];
		expect(facetCounts(rows, 'brand')).toHaveLength(1);
	});

	it('returns an empty array for no offers', () => {
		expect(facetCounts([], 'brand')).toEqual([]);
	});
});
