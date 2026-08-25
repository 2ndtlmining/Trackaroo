// Grouping for the /products index. Pure, so the ordering rule is pinned by
// tests rather than by how the page happens to render.
import { GENERIC_TIER_LABELS, generationTierLabel } from './tiers';
import type { Category, GenerationTier } from './types';

export interface IndexGroup<T> {
	key: string;
	brand: string;
	label: string;
	items: T[];
}

interface Groupable {
	brand: string;
	model: string;
	category: Category;
	generationTier: GenerationTier | null;
}

// Newest first. Anything untagged sorts last rather than vanishing — a product
// with no generation is a watchlist gap, not a reason to hide it.
const TIER_ORDER: Record<string, number> = { current: 0, 'current-1': 1, 'current-2': 2 };

export function groupForIndex<T extends Groupable>(items: T[]): IndexGroup<T>[] {
	const byKey = new Map<string, IndexGroup<T>>();
	const brandCount = new Map<string, number>();

	for (const item of items) {
		brandCount.set(item.brand, (brandCount.get(item.brand) ?? 0) + 1);
		const tier = item.generationTier ?? 'unknown';
		const key = `${item.brand}::${tier}`;
		let group = byKey.get(key);
		if (!group) {
			const label =
				generationTierLabel(item.brand, item.category, item.generationTier) ??
				GENERIC_TIER_LABELS.current;
			group = { key, brand: item.brand, label, items: [] };
			byKey.set(key, group);
		}
		group.items.push(item);
	}

	for (const group of byKey.values()) {
		group.items.sort((a, b) => a.model.localeCompare(b.model));
	}

	// Brand-major: buying is brand-anchored, so a brand's generations stay
	// adjacent. Biggest catalogue leads, so adding a brand does not reshuffle
	// the page and a one-product brand cannot jump the queue.
	return [...byKey.values()].sort((a, b) => {
		const byBrand = (brandCount.get(b.brand) ?? 0) - (brandCount.get(a.brand) ?? 0);
		if (byBrand !== 0) return byBrand;
		if (a.brand !== b.brand) return a.brand.localeCompare(b.brand);
		const tierA = TIER_ORDER[a.key.split('::')[1]] ?? 99;
		const tierB = TIER_ORDER[b.key.split('::')[1]] ?? 99;
		return tierA - tierB;
	});
}
