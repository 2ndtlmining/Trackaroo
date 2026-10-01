import { describe, it, expect } from 'vitest';
import { groupForIndex } from '../src/lib/productIndex';

const p = (brand: string, model: string, tier: string | null) =>
	({ brand, model, generationTier: tier, category: 'gpu' }) as never;

const items = [
	p('NVIDIA', 'GeForce RTX 4070', 'current-1'),
	p('AMD', 'Radeon RX 9070', 'current'),
	p('NVIDIA', 'GeForce RTX 5070', 'current'),
	p('NVIDIA', 'GeForce RTX 5060', 'current'),
	p('AMD', 'Radeon RX 7600', 'current-1')
];

describe('groupForIndex', () => {
	it('keeps a brand together, biggest catalogue first', () => {
		expect(groupForIndex(items).map((g) => g.brand)).toEqual(['NVIDIA', 'NVIDIA', 'AMD', 'AMD']);
	});

	it('puts the newest generation first within a brand', () => {
		const nvidia = groupForIndex(items).filter((g) => g.brand === 'NVIDIA');
		expect(nvidia[0].label).toContain('RTX 50');
		expect(nvidia[1].label).toContain('RTX 40');
	});

	it('labels groups from the shared generation labels', () => {
		expect(groupForIndex(items)[0].label).toBe('RTX 50 (Blackwell)');
	});

	it('sorts models within a group', () => {
		expect(groupForIndex(items)[0].items.map((i: { model: string }) => i.model)).toEqual([
			'GeForce RTX 5060',
			'GeForce RTX 5070'
		]);
	});

	it('loses nothing — every product lands in exactly one group', () => {
		const groups = groupForIndex(items);
		expect(groups.reduce((n, g) => n + g.items.length, 0)).toBe(items.length);
	});

	it('keeps an untagged product visible under a fallback heading', () => {
		const g = groupForIndex([p('Intel', 'Arc B580', null)]);
		expect(g).toHaveLength(1);
		expect(g[0].items).toHaveLength(1);
		expect(g[0].label).toBeTruthy();
	});

	it('handles an empty catalogue', () => {
		expect(groupForIndex([])).toEqual([]);
	});
});

describe('groupForIndex never-listed ordering (#23)', () => {
	it('sinks never-listed products to the bottom of their group', () => {
		const rows = [
			{ ...(p('NVIDIA', 'GeForce RTX 5060', 'current') as object), neverListed: true },
			{ ...(p('NVIDIA', 'GeForce RTX 5090', 'current') as object), neverListed: false },
			{ ...(p('NVIDIA', 'GeForce RTX 5070', 'current') as object), neverListed: false }
		] as never[];
		expect(groupForIndex(rows)[0].items.map((i: { model: string }) => i.model)).toEqual([
			'GeForce RTX 5070',
			'GeForce RTX 5090',
			'GeForce RTX 5060'
		]);
	});
});
