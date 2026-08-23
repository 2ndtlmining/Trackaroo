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
