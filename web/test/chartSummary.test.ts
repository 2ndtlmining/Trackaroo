import { describe, expect, it } from 'vitest';
import { chartSummary } from '../src/lib/chartSummary';

describe('chartSummary (#27)', () => {
	it('gives a screen reader the range, the span and today', () => {
		expect(
			chartSummary(
				[
					{ date: '2026-08-09', price: 8599 },
					{ date: '2026-09-23', price: 6599 }
				],
				8599
			)
		).toBe(
			'Price history chart. The cheapest in-stock price ranged from $6,599 to $8,599 between 9 Aug 2026 and 23 Sep 2026. Today $8,599.'
		);
	});

	it('handles a flat price and no stock today', () => {
		expect(
			chartSummary(
				[
					{ date: '2026-09-01', price: 500 },
					{ date: '2026-09-02', price: 500 }
				],
				null
			)
		).toBe(
			'Price history chart. The cheapest in-stock price held at $500 between 1 Sep 2026 and 2 Sep 2026. Nothing in stock today.'
		);
	});

	it('handles no data', () => {
		expect(chartSummary([], null)).toBe('Price history chart. No in-stock price recorded yet.');
	});
});
