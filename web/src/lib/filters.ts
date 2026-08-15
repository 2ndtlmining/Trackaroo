import type { Category, GenerationTier, ListingFilters, Retailer } from './types';

export const CATEGORY_OPTIONS: { value: Category; label: string }[] = [
	{ value: 'cpu', label: 'CPU' },
	{ value: 'gpu', label: 'GPU' }
];

export const RETAILER_OPTIONS: { value: Retailer; label: string }[] = [
	{ value: 'scorptec', label: 'Scorptec' },
	{ value: 'pccg', label: 'PCCG' },
	{ value: 'mwave', label: 'Mwave' }
];

export const TIER_OPTIONS: { value: GenerationTier; label: string }[] = [
	{ value: 'current', label: 'Current gen' },
	{ value: 'current-1', label: 'Previous gen' },
	{ value: 'current-2', label: 'Two gens back' }
];

const CATEGORIES: readonly string[] = CATEGORY_OPTIONS.map((o) => o.value);
const RETAILERS: readonly string[] = RETAILER_OPTIONS.map((o) => o.value);
const TIERS: readonly string[] = TIER_OPTIONS.map((o) => o.value);

export function parseFilters(searchParams: URLSearchParams): ListingFilters {
	const filters: ListingFilters = {};
	const category = searchParams.get('category');
	if (category && CATEGORIES.includes(category)) filters.category = category as Category;
	const retailer = searchParams.get('retailer');
	if (retailer && RETAILERS.includes(retailer)) filters.retailer = retailer as Retailer;
	const brand = searchParams.get('brand');
	if (brand) filters.brand = brand;
	const tier = searchParams.get('tier');
	if (tier && TIERS.includes(tier)) filters.generation_tier = tier as GenerationTier;
	return filters;
}

export function updateFilter(
	searchParams: URLSearchParams,
	key: keyof ListingFilters,
	value: string | null
): URLSearchParams {
	const next = new URLSearchParams(searchParams);
	const urlKey = key === 'generation_tier' ? 'tier' : key;
	if (value) next.set(urlKey, value);
	else next.delete(urlKey);
	return next;
}

export function hasActiveFilters(filters: ListingFilters): boolean {
	return Boolean(filters.category || filters.retailer || filters.brand || filters.generation_tier);
}

export function labelFor(options: readonly { value: string; label: string }[], value: string | undefined): string {
	if (!value) return '';
	return options.find((o) => o.value === value)?.label ?? value;
}
