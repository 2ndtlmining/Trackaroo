import { describe, expect, it } from 'vitest';
import type { ListingDisplay } from '../src/lib/offers';
import { deltaPresentation, deltaVsAvg30, offerTier, sortOffers } from '../src/lib/offers';
import { offer } from './helpers/offers';

describe('deltaVsAvg30', () => {
	it('computes the percent delta of a price against the average', () => {
		expect(deltaVsAvg30(1288, 1400)).toBeCloseTo(-8, 1);
		expect(deltaVsAvg30(1500, 1400)).toBeCloseTo(7.14, 1);
	});

	it('returns exactly 0 for a price that equals the average, not a tiny float error', () => {
		expect(deltaVsAvg30(189, 189)).toBe(0);
	});

	it('is null when the price or the average is missing, or the average is 0', () => {
		expect(deltaVsAvg30(null, 1400)).toBeNull();
		expect(deltaVsAvg30(1299, null)).toBeNull();
		expect(deltaVsAvg30(1299, 0)).toBeNull();
	});
});

describe('deltaPresentation', () => {
	it('treats a negative delta as down: a filled triangle and the down colour', () => {
		expect(deltaPresentation(-8)).toEqual({ arrow: '▼', class: 'text-down' });
	});

	it('treats a positive delta as up', () => {
		expect(deltaPresentation(7)).toEqual({ arrow: '▲', class: 'text-up' });
	});

	it('treats exactly zero as neutral — never an arrow or a directional colour', () => {
		expect(deltaPresentation(0)).toEqual({ arrow: '·', class: 'text-text-muted' });
	});
});

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

import { buildOfferView, OFFER_PAGE_SIZE, type OfferFilters } from '../src/lib/offers';

const NO_FILTERS: OfferFilters = { inStockOnly: false, retailer: null, brand: null, query: '' };

function manyOffers(n: number, overrides: Partial<ListingDisplay> = {}): ListingDisplay[] {
	return Array.from({ length: n }, (_, i) =>
		offer({ listingId: i + 1, latestPrice: 1000 + i, ...overrides })
	);
}

describe('buildOfferView volume control', () => {
	it('caps the visible list at OFFER_PAGE_SIZE and offers an expander', () => {
		const view = buildOfferView(manyOffers(31), NO_FILTERS, false);
		expect(view.visible).toHaveLength(OFFER_PAGE_SIZE);
		expect(view.matched).toBe(31);
		expect(view.showExpander).toBe(true);
	});

	it('shows every offer when expanded', () => {
		const view = buildOfferView(manyOffers(31), NO_FILTERS, true);
		expect(view.visible).toHaveLength(31);
	});

	it('renders no expander at or below the page size', () => {
		expect(buildOfferView(manyOffers(8), NO_FILTERS, false).showExpander).toBe(false);
		expect(buildOfferView(manyOffers(9), NO_FILTERS, false).showExpander).toBe(true);
	});

	it('applies the stock filter BEFORE the cap so the expander total matches the filter', () => {
		const rows = [
			...manyOffers(18),
			...manyOffers(13, { inStock: false, latestStock: 'out_of_stock' }).map((o, i) => ({
				...o,
				listingId: 100 + i
			}))
		];
		const view = buildOfferView(rows, { ...NO_FILTERS, inStockOnly: true }, false);
		expect(view.visible).toHaveLength(OFFER_PAGE_SIZE);
		expect(view.matched).toBe(18);
		expect(view.total).toBe(31);
		expect(view.visible.every((o) => o.inStock)).toBe(true);
	});

	it('auto-disables the stock filter when nothing is in stock, rather than rendering empty', () => {
		const rows = manyOffers(4, { inStock: false, latestStock: 'out_of_stock' });
		const view = buildOfferView(rows, { ...NO_FILTERS, inStockOnly: true }, false);
		expect(view.stockFilterForcedOff).toBe(true);
		expect(view.stockFilterApplied).toBe(false);
		expect(view.visible).toHaveLength(4);
	});

	it('reports inStockCount for the "18 of 31" label', () => {
		const rows = [
			...manyOffers(18),
			...manyOffers(13, { inStock: false, latestStock: 'out_of_stock' }).map((o, i) => ({
				...o,
				listingId: 100 + i
			}))
		];
		const view = buildOfferView(rows, NO_FILTERS, false);
		expect(view.inStockCount).toBe(18);
		expect(view.total).toBe(31);
	});

	it('re-computes the expander total when a chip filter narrows the set', () => {
		const rows = [
			...manyOffers(10, { retailer: 'scorptec' }),
			...manyOffers(10, { retailer: 'pccg' }).map((o, i) => ({ ...o, listingId: 100 + i }))
		];
		const view = buildOfferView(rows, { ...NO_FILTERS, retailer: 'pccg' }, false);
		expect(view.matched).toBe(10);
		expect(view.visible).toHaveLength(OFFER_PAGE_SIZE);
		expect(view.visible.every((o) => o.retailer === 'pccg')).toBe(true);
	});

	it('filters by brand chip', () => {
		const rows = [offer({ listingId: 1, brand: 'ASUS' }), offer({ listingId: 2, brand: 'MSI' })];
		const view = buildOfferView(rows, { ...NO_FILTERS, brand: 'MSI' }, false);
		expect(view.visible.map((o) => o.listingId)).toEqual([2]);
	});

	it('matches the free-text query against variant name and retailer, case-insensitively', () => {
		const rows = [
			offer({ listingId: 1, variantName: 'ASUS TUF RTX 5070 Ti OC' }),
			offer({ listingId: 2, variantName: 'MSI Ventus RTX 5070 Ti' })
		];
		expect(buildOfferView(rows, { ...NO_FILTERS, query: 'tuf' }, false).visible).toHaveLength(1);
		expect(buildOfferView(rows, { ...NO_FILTERS, query: '  ' }, false).visible).toHaveLength(2);
	});

	it('returns the cheapest in-stock offer first', () => {
		const rows = [
			offer({ listingId: 1, latestPrice: 1499 }),
			offer({ listingId: 2, latestPrice: 1099 })
		];
		expect(buildOfferView(rows, NO_FILTERS, false).visible[0].listingId).toBe(2);
	});

	it('handles an empty offer list', () => {
		const view = buildOfferView([], NO_FILTERS, false);
		expect(view.visible).toEqual([]);
		expect(view.showExpander).toBe(false);
		expect(view.stockFilterForcedOff).toBe(false);
	});
});

import { applyStockFilter } from '../src/lib/offers';

describe('applyStockFilter', () => {
	it('keeps only in-stock offers when the filter is on and something is in stock', () => {
		const rows = [
			offer({ listingId: 1 }),
			offer({ listingId: 2, inStock: false, latestStock: 'out_of_stock' })
		];
		const result = applyStockFilter(rows, true);
		expect(result.applied).toBe(true);
		expect(result.forcedOff).toBe(false);
		expect(result.offers.map((o) => o.listingId)).toEqual([1]);
	});

	it('forces the filter off and returns everything when nothing is in stock', () => {
		const rows = [
			offer({ listingId: 1, inStock: false, latestStock: 'out_of_stock' }),
			offer({ listingId: 2, inStock: false, latestStock: 'out_of_stock' })
		];
		const result = applyStockFilter(rows, true);
		expect(result.forcedOff).toBe(true);
		expect(result.applied).toBe(false);
		expect(result.offers).toHaveLength(2);
	});

	it('returns everything unfiltered when the filter is off', () => {
		const rows = [offer({ listingId: 1 }), offer({ listingId: 2, inStock: false })];
		const result = applyStockFilter(rows, false);
		expect(result.applied).toBe(false);
		expect(result.offers).toHaveLength(2);
	});

	it('never forces off an empty list (there is nothing to render either way)', () => {
		const result = applyStockFilter([], true);
		expect(result.forcedOff).toBe(false);
		expect(result.offers).toEqual([]);
	});
});
