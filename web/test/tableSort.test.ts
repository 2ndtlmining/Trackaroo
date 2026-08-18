import { describe, expect, it } from 'vitest';
import { nextSortDir, sortRows, type SortDir } from '../src/lib/tableSort';

describe('nextSortDir', () => {
	it('cycles unsorted -> asc -> desc -> unsorted', () => {
		let dir: SortDir = null;
		expect(nextSortDir(dir)).toBe('asc');
		dir = 'asc';
		expect(nextSortDir(dir)).toBe('desc');
		dir = 'desc';
		expect(nextSortDir(dir)).toBe(null);
	});
});

describe('sortRows', () => {
	const rows = [
		{ id: 1, price: 300 },
		{ id: 2, price: 100 },
		{ id: 3, price: null },
		{ id: 4, price: 200 }
	];

	it('returns a copy when unsorted', () => {
		const out = sortRows(rows, null, (r) => r.price);
		expect(out).not.toBe(rows);
		expect(out.map((r) => r.id)).toEqual([1, 2, 3, 4]);
	});

	it('sorts numbers ascending with nulls last', () => {
		const out = sortRows(rows, 'asc', (r) => r.price);
		expect(out.map((r) => r.id)).toEqual([2, 4, 1, 3]);
	});

	it('sorts numbers descending with nulls last', () => {
		const out = sortRows(rows, 'desc', (r) => r.price);
		expect(out.map((r) => r.id)).toEqual([1, 4, 2, 3]);
	});

	it('sorts strings with numeric-aware comparison', () => {
		const models = [{ m: 'RTX 5070' }, { m: 'RTX 5090' }, { m: 'RTX 5080' }];
		const out = sortRows(models, 'asc', (r) => r.m);
		expect(out.map((r) => r.m)).toEqual(['RTX 5070', 'RTX 5080', 'RTX 5090']);
	});
});