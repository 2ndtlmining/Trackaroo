import { describe, expect, it } from 'vitest';
import { generationTierLabel, GENERIC_TIER_LABELS } from '../src/lib/tiers';

describe('generationTierLabel', () => {
	it('maps AMD CPU tiers to Ryzen generations', () => {
		expect(generationTierLabel('AMD', 'cpu', 'current')).toBe('Ryzen 9000 (Zen 5)');
		expect(generationTierLabel('AMD', 'cpu', 'current-1')).toBe('Ryzen 7000 (Zen 4)');
		expect(generationTierLabel('AMD', 'cpu', 'current-2')).toBe('Ryzen 5000 (Zen 3)');
	});

	it('maps Intel CPU tiers to Core generations', () => {
		expect(generationTierLabel('Intel', 'cpu', 'current')).toBe('Core Ultra 200 (Arrow Lake)');
		expect(generationTierLabel('Intel', 'cpu', 'current-1')).toBe('Core 14th Gen');
		expect(generationTierLabel('Intel', 'cpu', 'current-2')).toBe('Core 13th Gen');
	});

	it('maps NVIDIA GPU tiers to GeForce generations', () => {
		expect(generationTierLabel('NVIDIA', 'gpu', 'current')).toBe('RTX 50 (Blackwell)');
		expect(generationTierLabel('NVIDIA', 'gpu', 'current-1')).toBe('RTX 40 (Ada)');
		expect(generationTierLabel('NVIDIA', 'gpu', 'current-2')).toBe('RTX 30 (Ampere)');
	});

	it('maps AMD GPU tiers to Radeon generations', () => {
		expect(generationTierLabel('AMD', 'gpu', 'current')).toBe('RX 9000 (RDNA 4)');
		expect(generationTierLabel('AMD', 'gpu', 'current-1')).toBe('RX 7000 (RDNA 3)');
		expect(generationTierLabel('AMD', 'gpu', 'current-2')).toBe('RX 6000 (RDNA 2)');
	});

	it('falls back to generic labels for unmapped lines (Intel Arc)', () => {
		expect(generationTierLabel('Intel', 'gpu', 'current')).toBe(GENERIC_TIER_LABELS.current);
		expect(generationTierLabel('Intel', 'gpu', 'current-1')).toBe(GENERIC_TIER_LABELS['current-1']);
	});

	it('is case-insensitive on brand and category', () => {
		expect(generationTierLabel('amd', 'CPU', 'current')).toBe('Ryzen 9000 (Zen 5)');
		expect(generationTierLabel('nvidia', 'GPU', 'current-1')).toBe('RTX 40 (Ada)');
	});

	it('returns null when the tier is missing', () => {
		expect(generationTierLabel('AMD', 'cpu', null)).toBeNull();
		expect(generationTierLabel('AMD', 'cpu', undefined)).toBeNull();
	});
});