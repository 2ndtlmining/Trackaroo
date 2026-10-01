// Product pages were dead ends: no nav item lit up and nothing led back to the
// category (#26). The middle crumb searches the index for the brand -- the
// index has no brand facet, and its search matches brands.
import { generationTierLabel } from './tiers';
import type { Category, GenerationTier } from './types';

export interface Crumb {
	label: string;
	href: string | null;
}

export function productBreadcrumbs(p: {
	category: Category;
	brand: string;
	model: string;
	generation_tier: GenerationTier | null;
}): Crumb[] {
	const tier = generationTierLabel(p.brand, p.category, p.generation_tier);
	return [
		{ label: p.category === 'cpu' ? 'CPUs' : 'GPUs', href: `/products?category=${p.category}` },
		{
			label: tier ? `${p.brand} ${tier}` : p.brand,
			href: `/products?category=${p.category}&q=${encodeURIComponent(p.brand)}`
		},
		{ label: p.model, href: null }
	];
}
