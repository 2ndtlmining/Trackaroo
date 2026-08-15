import { describe, expect, it } from 'vitest';
import {
	CATEGORY_OPTIONS,
	RETAILER_OPTIONS,
	TIER_OPTIONS,
	hasActiveFilters,
	labelFor,
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

	it('ignores invalid enum values', () => {
		const params = new URLSearchParams('category=ram&retailer=ebay&tier=ancient');
		expect(parseFilters(params)).toEqual({});
	});

	it('keeps brand even when other values are invalid', () => {
		const params = new URLSearchParams('category=ram&brand=NVIDIA');
		expect(parseFilters(params)).toEqual({ brand: 'NVIDIA' });
	});

	it('accepts every option value from the option lists', () => {
		for (const opt of [...CATEGORY_OPTIONS, ...RETAILER_OPTIONS, ...TIER_OPTIONS]) {
			const params = new URLSearchParams();
			if (opt.value === 'cpu' || opt.value === 'gpu') params.set('category', opt.value);
			else if (opt.value === 'scorptec' || opt.value === 'pccg' || opt.value === 'mwave')
				params.set('retailer', opt.value);
			else params.set('tier', opt.value);
			const parsed = parseFilters(params);
			const value = parsed.category ?? parsed.retailer ?? parsed.generation_tier;
			expect(value).toBe(opt.value);
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
	});
});

describe('labelFor', () => {
	it('returns the option label for a known value', () => {
		expect(labelFor(RETAILER_OPTIONS, 'pccg')).toBe('PCCG');
		expect(labelFor(TIER_OPTIONS, 'current-1')).toBe('Previous gen');
	});

	it('returns empty string for undefined', () => {
		expect(labelFor(CATEGORY_OPTIONS, undefined)).toBe('');
	});

	it('falls back to the raw value for unknown values', () => {
		expect(labelFor(CATEGORY_OPTIONS, 'mystery')).toBe('mystery');
	});
});
