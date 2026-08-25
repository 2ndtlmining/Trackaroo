import { describe, it, expect } from 'vitest';
import { searchProducts } from '../src/lib/productSearch';

const items = [
	{ model: 'GeForce RTX 5070', brand: 'NVIDIA', productVariant: null },
	{ model: 'GeForce RTX 5070 Ti', brand: 'NVIDIA', productVariant: null },
	{ model: 'GeForce RTX 4070', brand: 'NVIDIA', productVariant: null },
	{ model: 'Radeon RX 9070 XT', brand: 'AMD', productVariant: null },
	{ model: 'Ryzen 5 5600', brand: 'AMD', productVariant: null }
];

describe('searchProducts', () => {
	it('returns everything for an empty query', () => {
		expect(searchProducts(items, '   ')).toHaveLength(5);
	});

	it('matches a substring of the model without false positives', () => {
		// 9070 must not match 5070 — a digit-substring bug here would be
		// invisible in the UI but put the wrong card at the top.
		expect(searchProducts(items, '5070').map((i) => i.model)).toEqual([
			'GeForce RTX 5070',
			'GeForce RTX 5070 Ti'
		]);
	});

	it('ranks an exact model match above a longer one that merely starts with it', () => {
		const r = searchProducts(items, 'geforce rtx 5070');
		expect(r.map((i) => i.model)).toEqual(['GeForce RTX 5070', 'GeForce RTX 5070 Ti']);
	});

	it('requires every term, in any order', () => {
		expect(searchProducts(items, '5070 ti').map((i) => i.model)).toEqual(['GeForce RTX 5070 Ti']);
		expect(searchProducts(items, 'ti 5070').map((i) => i.model)).toEqual(['GeForce RTX 5070 Ti']);
	});

	it('matches on brand when the model does not contain the term', () => {
		expect(searchProducts(items, 'amd').map((i) => i.model)).toEqual([
			'Radeon RX 9070 XT',
			'Ryzen 5 5600'
		]);
	});

	it('ranks a model match above a brand-only match', () => {
		const r = searchProducts(
			[
				{ model: 'Radeon RX 9070 XT', brand: 'AMD', productVariant: null },
				{ model: 'AMD Special', brand: 'NVIDIA', productVariant: null }
			],
			'amd'
		);
		expect(r[0].model).toBe('AMD Special');
	});

	it('is case and whitespace insensitive', () => {
		expect(searchProducts(items, '  RyZeN   5600 ').map((i) => i.model)).toEqual(['Ryzen 5 5600']);
	});

	it('returns nothing when any term matches nothing', () => {
		expect(searchProducts(items, '5070 banana')).toEqual([]);
	});

	it('breaks ties on model name so ordering is stable', () => {
		const a = searchProducts(items, 'geforce').map((i) => i.model);
		const b = searchProducts([...items].reverse(), 'geforce').map((i) => i.model);
		expect(a).toEqual(b);
		expect(a).toEqual(['GeForce RTX 4070', 'GeForce RTX 5070', 'GeForce RTX 5070 Ti']);
	});
});
