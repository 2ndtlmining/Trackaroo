import { describe, expect, it } from 'vitest';
import { buildDisplayNames, displayName } from '../src/lib/displayName';

const item = (id: number, model: string, vramGb: number | null, category: 'gpu' | 'cpu' = 'gpu') => ({
	id,
	category,
	model,
	vramGb
});

describe('buildDisplayNames (Phase 4 follow-up)', () => {
	const names = buildDisplayNames([
		item(1, 'GeForce RTX 5060 Ti', 16),
		item(2, 'GeForce RTX 5060 Ti 8GB', 8),
		item(3, 'GeForce RTX 5060', 8),
		item(4, 'Radeon RX 9070', 16),
		item(5, 'Ryzen 5 5600', null, 'cpu')
	]);

	it('labels the base card with its memory when a "<model> <N>GB" sibling exists', () => {
		expect(names.get(1)).toBe('GeForce RTX 5060 Ti 16GB');
	});

	it('leaves the sibling, unrelated cards and CPUs alone', () => {
		expect(names.get(2)).toBe('GeForce RTX 5060 Ti 8GB');
		// "GeForce RTX 5060 Ti 8GB" is not a memory sibling of "GeForce RTX 5060".
		expect(names.get(3)).toBe('GeForce RTX 5060');
		expect(names.get(4)).toBe('Radeon RX 9070');
		expect(names.get(5)).toBe('Ryzen 5 5600');
	});

	it('needs a known VRAM to add one', () => {
		const n = buildDisplayNames([item(1, 'Radeon RX 9060 XT', null), item(2, 'Radeon RX 9060 XT 8GB', 8)]);
		expect(n.get(1)).toBe('Radeon RX 9060 XT');
	});

	it('falls back to the stored model for an unknown id', () => {
		expect(displayName(names, 999, 'Arc B580')).toBe('Arc B580');
	});
});
