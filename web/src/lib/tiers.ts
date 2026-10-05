import type { TierLabels } from './models';
import type { GenerationTier } from './types';

export const GENERIC_TIER_LABELS: Record<GenerationTier, string> = {
	current: 'Current gen',
	'current-1': 'Previous gen',
	'current-2': 'Two gens back'
};

// Labels come from the DB (getTierLabels, via the root layout's data), so a
// new series shows its own name without a web rebuild (#17).
export function generationTierLabel(
	labels: TierLabels,
	brand: string,
	category: string,
	tier: GenerationTier | null | undefined
): string | null {
	if (!tier) return null;
	const line = `${brand.toLowerCase()}-${category.toLowerCase()}`;
	return labels[line]?.[tier] ?? GENERIC_TIER_LABELS[tier];
}
