import { describe, expect, it } from 'vitest';
import { axisStartsAtZero, gapSegments } from '../src/lib/chartExtras';

describe('chartExtras', () => {
	it('finds gaps between known points', () => {
		expect(gapSegments(['d1', 'd2', 'd3', 'd4', 'd5'], [10, null, null, 12, 13])).toEqual([
			{ from: 0, to: 3 }
		]);
		expect(gapSegments(['d1', 'd2'], [10, 11])).toEqual([]);
		expect(gapSegments(['d1', 'd2', 'd3'], [null, 5, null])).toEqual([]);
	});
	it('finds several gaps', () => {
		expect(gapSegments(['a', 'b', 'c', 'd', 'e'], [1, null, 2, null, 3])).toEqual([
			{ from: 0, to: 2 },
			{ from: 2, to: 4 }
		]);
	});
	it('axis note only when the minimum is above zero', () => {
		expect(axisStartsAtZero(0)).toBe(true);
		expect(axisStartsAtZero(450)).toBe(false);
	});
});
