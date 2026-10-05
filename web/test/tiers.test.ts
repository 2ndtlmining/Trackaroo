import { describe, expect, it } from 'vitest';
import { LABELS } from './helpers/tierLabels';
import { generationTierLabel, GENERIC_TIER_LABELS } from '../src/lib/tiers';

describe('generationTierLabel', () => {
	it('maps AMD CPU tiers to Ryzen generations', () => {
		expect(generationTierLabel(LABELS, 'AMD', 'cpu', 'current')).toBe('Ryzen 9000 (Zen 5)');
		expect(generationTierLabel(LABELS, 'AMD', 'cpu', 'current-1')).toBe('Ryzen 7000 (Zen 4)');
		expect(generationTierLabel(LABELS, 'AMD', 'cpu', 'current-2')).toBe('Ryzen 5000 (Zen 3)');
	});

	it('maps Intel CPU tiers to Core generations', () => {
		expect(generationTierLabel(LABELS, 'Intel', 'cpu', 'current')).toBe('Core Ultra 200 (Arrow Lake)');
		expect(generationTierLabel(LABELS, 'Intel', 'cpu', 'current-1')).toBe('Core 14th Gen');
		expect(generationTierLabel(LABELS, 'Intel', 'cpu', 'current-2')).toBe('Core 13th Gen');
	});

	it('maps NVIDIA GPU tiers to GeForce generations', () => {
		expect(generationTierLabel(LABELS, 'NVIDIA', 'gpu', 'current')).toBe('RTX 50 (Blackwell)');
		expect(generationTierLabel(LABELS, 'NVIDIA', 'gpu', 'current-1')).toBe('RTX 40 (Ada)');
		expect(generationTierLabel(LABELS, 'NVIDIA', 'gpu', 'current-2')).toBe('RTX 30 (Ampere)');
	});

	it('maps AMD GPU tiers to Radeon generations', () => {
		expect(generationTierLabel(LABELS, 'AMD', 'gpu', 'current')).toBe('RX 9000 (RDNA 4)');
		expect(generationTierLabel(LABELS, 'AMD', 'gpu', 'current-1')).toBe('RX 7000 (RDNA 3)');
		expect(generationTierLabel(LABELS, 'AMD', 'gpu', 'current-2')).toBe('RX 6000 (RDNA 2)');
	});

	// Arc used to fall back to "Current gen", which lumped Alchemist and
	// Battlemage under one heading on the product index.
	it('names the Intel Arc generations', () => {
		expect(generationTierLabel(LABELS, 'Intel', 'gpu', 'current')).toBe('Arc B (Battlemage)');
		expect(generationTierLabel(LABELS, 'Intel', 'gpu', 'current-1')).toBe('Arc A (Alchemist)');
	});

	it('gives generic labels when no labels are loaded', () => {
		expect(generationTierLabel({}, 'NVIDIA', 'gpu', 'current')).toBe(GENERIC_TIER_LABELS.current);
	});

	it('still falls back to generic labels for a line with no mapping', () => {
		expect(generationTierLabel(LABELS, 'Someshop', 'gpu', 'current')).toBe(GENERIC_TIER_LABELS.current);
		expect(generationTierLabel(LABELS, 'Someshop', 'gpu', 'current-1')).toBe(
			GENERIC_TIER_LABELS['current-1']
		);
	});

	it('is case-insensitive on brand and category', () => {
		expect(generationTierLabel(LABELS, 'amd', 'CPU', 'current')).toBe('Ryzen 9000 (Zen 5)');
		expect(generationTierLabel(LABELS, 'nvidia', 'GPU', 'current-1')).toBe('RTX 40 (Ada)');
	});

	it('returns null when the tier is missing', () => {
		expect(generationTierLabel(LABELS, 'AMD', 'cpu', null)).toBeNull();
		expect(generationTierLabel(LABELS, 'AMD', 'cpu', undefined)).toBeNull();
	});
});