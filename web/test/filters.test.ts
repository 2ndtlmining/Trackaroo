import { describe, expect, it } from 'vitest';
import {
	CATEGORY_OPTIONS,
	RETAILER_OPTIONS,
	TIER_OPTIONS,
	hasActiveFilters,
	parseFilters,
	updateFilter
} from '../src/lib/filters';

describe('parseFilters', () => {
	it('returns empty filters for empty params', () => {
		expect(parseFilters(new URLSearchParams())).toEqual({});
	});

	it('parses valid category, retailer, brand and tier', () => {
		const params = new URLSearchParams('category=gpu&retailer=pccg&brand=AMD&tier=current-1');
		expect(parseFilters(params)).toEqual({
			category: 'gpu',
			retailer: 'pccg',
			brand: 'AMD',
			generation_tier: 'current-1'
		});
	});

	it('parses a search query param', () => {
		const params = new URLSearchParams('q=rtx+5090');
		expect(parseFilters(params)).toEqual({ query: 'rtx 5090' });
	});

	it('parses a sort param', () => {
		expect(parseFilters(new URLSearchParams('sort=price-asc')).sort).toBe('price-asc');
		expect(parseFilters(new URLSearchParams('sort=price-desc')).sort).toBe('price-desc');
		expect(parseFilters(new URLSearchParams('sort=bogus')).sort).toBeUndefined();
	});

	it('parses an in-stock flag', () => {
		expect(parseFilters(new URLSearchParams('in_stock=1'))).toEqual({ inStock: true });
		expect(parseFilters(new URLSearchParams('in_stock=true'))).toEqual({ inStock: true });
	});

	it('ignores in-stock params that are not enabled', () => {
		expect(parseFilters(new URLSearchParams('in_stock=0'))).toEqual({});
		expect(parseFilters(new URLSearchParams('in_stock=yes'))).toEqual({});
	});

	it('ignores invalid enum values', () => {
		const params = new URLSearchParams('category=ram&retailer=ebay&tier=ancient');
		expect(parseFilters(params)).toEqual({});
	});

	it('keeps brand even when other values are invalid', () => {
		const params = new URLSearchParams('category=ram&brand=NVIDIA');
		expect(parseFilters(params)).toEqual({ brand: 'NVIDIA' });
	});

	it('accepts every option value from the option lists', () => {
		// Dispatch by the list an option came from, not by hardcoded slugs —
		// the old version sent any unrecognised slug to `tier`, so adding a
		// retailer made this fail for a reason that had nothing to do with it.
		const cases: Array<{ key: 'category' | 'retailer' | 'tier'; value: string }> = [
			...CATEGORY_OPTIONS.map((o) => ({ key: 'category' as const, value: o.value as string })),
			...RETAILER_OPTIONS.map((o) => ({ key: 'retailer' as const, value: o.value as string })),
			...TIER_OPTIONS.map((o) => ({ key: 'tier' as const, value: o.value as string }))
		];
		for (const { key, value } of cases) {
			const params = new URLSearchParams();
			params.set(key, value);
			const parsed = parseFilters(params);
			const parsedValue = parsed.category ?? parsed.retailer ?? parsed.generation_tier;
			expect(parsedValue).toBe(value);
		}
	});
});

describe('updateFilter', () => {
	it('sets a value and returns a new params object', () => {
		const params = new URLSearchParams('category=cpu');
		const next = updateFilter(params, 'retailer', 'scorptec');
		expect(next.get('retailer')).toBe('scorptec');
		expect(params.get('retailer')).toBeNull();
	});

	it('maps generation_tier to the tier URL key', () => {
		const next = updateFilter(new URLSearchParams(), 'generation_tier', 'current-2');
		expect(next.get('tier')).toBe('current-2');
		expect(next.get('generation_tier')).toBeNull();
	});

	it('maps query to the q URL key', () => {
		const next = updateFilter(new URLSearchParams(), 'query', 'rtx 5090');
		expect(next.get('q')).toBe('rtx 5090');
		expect(next.get('query')).toBeNull();
	});

	it('maps sort to the sort URL key', () => {
		const next = updateFilter(new URLSearchParams(), 'sort', 'price-asc');
		expect(next.get('sort')).toBe('price-asc');
	});

	it('maps inStock to the in_stock URL key', () => {
		const next = updateFilter(new URLSearchParams(), 'inStock', '1');
		expect(next.get('in_stock')).toBe('1');
		expect(next.get('inStock')).toBeNull();
	});

	it('removes in_stock when inStock is cleared', () => {
		const params = new URLSearchParams('in_stock=1');
		const next = updateFilter(params, 'inStock', null);
		expect(next.get('in_stock')).toBeNull();
	});

	it('round-trips inStock with parseFilters', () => {
		const next = updateFilter(new URLSearchParams(), 'inStock', '1');
		expect(parseFilters(next)).toEqual({ inStock: true });
	});

	it('removes the key when value is null', () => {
		const params = new URLSearchParams('brand=AMD');
		const next = updateFilter(params, 'brand', null);
		expect(next.get('brand')).toBeNull();
	});

	it('round-trips with parseFilters', () => {
		const params = new URLSearchParams();
		const next = updateFilter(updateFilter(params, 'category', 'gpu'), 'generation_tier', 'current');
		expect(parseFilters(next)).toEqual({ category: 'gpu', generation_tier: 'current' });
	});
});

describe('hasActiveFilters', () => {
	it('is false for empty filters', () => {
		expect(hasActiveFilters({})).toBe(false);
	});

	it('is true when any filter is set', () => {
		expect(hasActiveFilters({ brand: 'AMD' })).toBe(true);
		expect(hasActiveFilters({ generation_tier: 'current' })).toBe(true);
		expect(hasActiveFilters({ query: '5090' })).toBe(true);
		expect(hasActiveFilters({ sort: 'price-asc' })).toBe(true);
		expect(hasActiveFilters({ inStock: true })).toBe(true);
	});
});

describe('six-retailer readiness', () => {
	it('offers all six retailers, Scorptec and PCCG first', () => {
		expect(RETAILER_OPTIONS.map((o) => o.value)).toEqual([
			'scorptec',
			'pccg',
			'mwave',
			'umart',
			'centrecom',
			'ple'
		]);
	});

	it('accepts a new retailer slug from the URL', () => {
		const filters = parseFilters(new URLSearchParams('retailer=mwave'));
		expect(filters.retailer).toBe('mwave');
	});

	it('still rejects an unknown slug', () => {
		const filters = parseFilters(new URLSearchParams('retailer=nope'));
		expect(filters.retailer).toBeUndefined();
	});
});
