import type { GenerationTier } from './types';

export const GENERIC_TIER_LABELS: Record<GenerationTier, string> = {
	current: 'Current gen',
	'current-1': 'Previous gen',
	'current-2': 'Two gens back'
};

const TIER_LINE_LABELS: Record<string, Record<GenerationTier, string>> = {
	'amd-cpu': {
		current: 'Ryzen 9000 (Zen 5)',
		'current-1': 'Ryzen 7000 (Zen 4)',
		'current-2': 'Ryzen 5000 (Zen 3)'
	},
	'intel-cpu': {
		current: 'Core Ultra 200 (Arrow Lake)',
		'current-1': 'Core 14th Gen',
		'current-2': 'Core 13th Gen'
	},
	'nvidia-gpu': {
		current: 'RTX 50 (Blackwell)',
		'current-1': 'RTX 40 (Ada)',
		'current-2': 'RTX 30 (Ampere)'
	},
	'amd-gpu': {
		current: 'RX 9000 (RDNA 4)',
		'current-1': 'RX 7000 (RDNA 3)',
		'current-2': 'RX 6000 (RDNA 2)'
	}
};

export function generationTierLabel(
	brand: string,
	category: string,
	tier: GenerationTier | null | undefined
): string | null {
	if (!tier) return null;
	const line = `${brand.toLowerCase()}-${category.toLowerCase()}`;
	return TIER_LINE_LABELS[line]?.[tier] ?? GENERIC_TIER_LABELS[tier];
}