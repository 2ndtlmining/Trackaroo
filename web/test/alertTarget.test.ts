import { describe, expect, it } from 'vitest';
import { MAX_TARGET_PRICE, parseTargetPrice } from '../src/lib/alertTarget';

describe('parseTargetPrice (#15)', () => {
	it('accepts a plain dollar amount', () => {
		expect(parseTargetPrice('899')).toBe(899);
	});

	it('rounds to whole cents', () => {
		expect(parseTargetPrice('899.999')).toBe(900);
		expect(parseTargetPrice('899.994')).toBe(899.99);
		expect(parseTargetPrice(' 12.5 ')).toBe(12.5);
	});

	it('rejects empty, non-numeric, zero, negative and non-finite input', () => {
		for (const raw of [null, '', '   ', 'abc', '0', '-5', '0.001', 'Infinity', 'NaN', '1e400']) {
			expect(parseTargetPrice(raw)).toBeNull();
		}
	});

	it('caps the target at MAX_TARGET_PRICE', () => {
		expect(parseTargetPrice(String(MAX_TARGET_PRICE))).toBe(MAX_TARGET_PRICE);
		expect(parseTargetPrice(String(MAX_TARGET_PRICE + 0.01))).toBeNull();
		expect(parseTargetPrice('1e9')).toBeNull();
	});
});
