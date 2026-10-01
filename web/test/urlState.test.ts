import { describe, expect, it } from 'vitest';
import { MAX_COMPARE, parseCompareIds, withParams } from '../src/lib/urlState';

describe('parseCompareIds (#26, Review Focus 3)', () => {
	it('reads a comma list', () => {
		expect(parseCompareIds('3,1,2')).toEqual([3, 1, 2]);
	});

	it('drops junk, zero, negatives and duplicates, and caps at four', () => {
		expect(parseCompareIds('abc,-1,0,5,5,6,7,8,9')).toEqual([5, 6, 7, 8]);
		expect(MAX_COMPARE).toBe(4);
	});

	it('is empty for a missing or blank parameter', () => {
		expect(parseCompareIds(null)).toEqual([]);
		expect(parseCompareIds('')).toEqual([]);
	});
});

describe('withParams', () => {
	it('sets, replaces and removes keys, keeping everything else in place', () => {
		expect(withParams('?category=gpu&in_stock=1', { q: '5070 ti', in_stock: null })).toBe(
			'?category=gpu&q=5070+ti'
		);
		expect(withParams('?category=gpu&q=old', { q: 'new' })).toBe('?category=gpu&q=new');
	});

	it('treats an empty string like null and can empty the query entirely', () => {
		expect(withParams('?q=x', { q: '' })).toBe('');
	});
});
