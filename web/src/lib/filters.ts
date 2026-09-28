import type { Category, GenerationTier, ListingFilters, ListingSort, Retailer } from './types';

export const CATEGORY_OPTIONS: { value: Category; label: string }[] = [
	{ value: 'cpu', label: 'CPU' },
	{ value: 'gpu', label: 'GPU' }
];

export const RETAILER_OPTIONS: { value: Retailer; label: string }[] = [
	{ value: 'scorptec', label: 'Scorptec' },
	{ value: 'pccg', label: 'PCCG' },
	{ value: 'mwave', label: 'MWave' },
	{ value: 'umart', label: 'Umart' },
	{ value: 'centrecom', label: 'Centre Com' },
	{ value: 'ple', label: 'PLE' }
];

export const TIER_OPTIONS: { value: GenerationTier; label: string }[] = [
	{ value: 'current', label: 'Current gen' },
	{ value: 'current-1', label: 'Previous gen' },
	{ value: 'current-2', label: 'Two gens back' }
];

const CATEGORIES: readonly string[] = CATEGORY_OPTIONS.map((o) => o.value);
const RETAILERS: readonly string[] = RETAILER_OPTIONS.map((o) => o.value);
const TIERS: readonly string[] = TIER_OPTIONS.map((o) => o.value);

const RETAILER_LABELS = new Map(RETAILER_OPTIONS.map((o) => [o.value as string, o.label]));

// The one place a retailer slug becomes a display name (#5).
export function retailerLabel(slug: string): string {
	return RETAILER_LABELS.get(slug) ?? slug;
}

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
	const query = searchParams.get('q');
	if (query) filters.query = query;
	const sort = searchParams.get('sort');
	if (sort === 'price-asc' || sort === 'price-desc') filters.sort = sort;
	const inStock = searchParams.get('in_stock');
	if (inStock === '1' || inStock === 'true') filters.inStock = true;
	return filters;
}

const URL_KEY: Record<keyof ListingFilters, string> = {
	category: 'category',
	retailer: 'retailer',
	brand: 'brand',
	generation_tier: 'tier',
	query: 'q',
	sort: 'sort',
	inStock: 'in_stock'
};

export function updateFilter(
	searchParams: URLSearchParams,
	key: keyof ListingFilters,
	value: string | null
): URLSearchParams {
	const next = new URLSearchParams(searchParams);
	const urlKey = URL_KEY[key];
	if (value) next.set(urlKey, value);
	else next.delete(urlKey);
	return next;
}

export const SORT_OPTIONS: { value: ListingSort; label: string }[] = [
	{ value: 'price-asc', label: 'Price: low to high' },
	{ value: 'price-desc', label: 'Price: high to low' }
];

export function hasActiveFilters(filters: ListingFilters): boolean {
	return Boolean(
		filters.category ||
			filters.retailer ||
			filters.brand ||
			filters.generation_tier ||
			filters.query ||
			filters.sort ||
			filters.inStock
	);
}
