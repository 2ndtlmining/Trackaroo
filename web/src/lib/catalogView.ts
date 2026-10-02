import { RETAILER_OPTIONS, TIER_OPTIONS } from './filters';
import { generationTierLabel } from './tiers';
import type { GenerationTier, Retailer } from './types';

export type CatalogSort = 'price' | 'name' | 'spec' | 'released' | 'listings';
export type SortDir = 'asc' | 'desc';

export interface CatalogView {
	max: number | null;
	brands: string[];
	gens: GenerationTier[];
	inStock: boolean;
	retailer: Retailer | null;
	sort: CatalogSort | null;
	dir: SortDir;
}

export interface CatalogRowInput {
	productId: number;
	brand: string;
	model: string;
	generationTier: GenerationTier | null;
	cheapestInStockPrice: number | null;
	retailerPrices: Partial<Record<Retailer, { inStock: number | null; any: number | null }>>;
	vramGb: number | null;
	cores: number | null;
	launchDate: string | null;
	listingCount: number;
	neverListed: boolean;
}

export const DEFAULT_DIR: Record<CatalogSort, SortDir> = {
	price: 'asc',
	name: 'asc',
	spec: 'desc',
	released: 'desc',
	listings: 'desc'
};

const BRANDS = ['NVIDIA', 'AMD', 'Intel'];
const SORTS = Object.keys(DEFAULT_DIR) as CatalogSort[];
const GENS: readonly string[] = TIER_OPTIONS.map((o) => o.value);
const RETAILERS: readonly string[] = RETAILER_OPTIONS.map((o) => o.value);
const MAX_PRICE = 100000;

// Repeated params and comma lists both work: ?brand=AMD,Intel&brand=NVIDIA.
function listValues(params: URLSearchParams, key: string): string[] {
	return params
		.getAll(key)
		.flatMap((v) => v.split(','))
		.map((v) => v.trim())
		.filter(Boolean);
}

export function parseCatalogView(params: URLSearchParams): CatalogView {
	const maxRaw = params.get('max');
	let max: number | null = null;
	if (maxRaw !== null && /^\d{1,6}$/.test(maxRaw)) {
		const n = Number(maxRaw);
		if (n >= 1 && n <= MAX_PRICE) max = n;
	}

	const brands: string[] = [];
	for (const raw of listValues(params, 'brand')) {
		const canon = BRANDS.find((b) => b.toLowerCase() === raw.toLowerCase());
		if (canon && !brands.includes(canon)) brands.push(canon);
	}

	const gens: GenerationTier[] = [];
	for (const raw of listValues(params, 'gen')) {
		if (GENS.includes(raw) && !gens.includes(raw as GenerationTier)) gens.push(raw as GenerationTier);
	}

	const retailerRaw = params.get('retailer');
	const retailer = retailerRaw && RETAILERS.includes(retailerRaw) ? (retailerRaw as Retailer) : null;

	const sortRaw = params.get('sort');
	const sort = sortRaw && (SORTS as string[]).includes(sortRaw) ? (sortRaw as CatalogSort) : null;
	const dirRaw = params.get('dir');
	const dir: SortDir = dirRaw === 'asc' || dirRaw === 'desc' ? dirRaw : sort ? DEFAULT_DIR[sort] : 'asc';

	return { max, brands, gens, inStock: params.get('in_stock') === '1', retailer, sort, dir };
}

export function catalogViewParams(view: CatalogView): Record<string, string | null> {
	return {
		max: view.max !== null ? String(view.max) : null,
		brand: view.brands.length ? view.brands.join(',') : null,
		gen: view.gens.length ? view.gens.join(',') : null,
		in_stock: view.inStock ? '1' : null,
		retailer: view.retailer,
		sort: view.sort,
		dir: view.sort && view.dir !== DEFAULT_DIR[view.sort] ? view.dir : null
	};
}

export function shownPrice(row: CatalogRowInput, view: CatalogView): number | null {
	if (!view.retailer) return row.cheapestInStockPrice;
	const entry = row.retailerPrices[view.retailer];
	if (!entry) return null;
	return view.inStock ? entry.inStock : entry.any;
}

function sortValue(row: CatalogRowInput, key: CatalogSort, view: CatalogView): number | string | null {
	switch (key) {
		case 'price': return shownPrice(row, view);
		case 'name': return row.model;
		case 'spec': return row.vramGb ?? row.cores;
		case 'released': return row.launchDate;
		case 'listings': return row.listingCount;
	}
}

const cmp = (a: number | string, b: number | string) => (a < b ? -1 : a > b ? 1 : 0);

export function applyCatalogView<T extends CatalogRowInput>(rows: T[], view: CatalogView): T[] {
	const kept = rows.filter((r) => {
		if (view.brands.length && !view.brands.includes(r.brand)) return false;
		if (view.gens.length && (!r.generationTier || !view.gens.includes(r.generationTier))) return false;
		const price = shownPrice(r, view);
		// A retailer filter keeps only products priced there; in_stock needs an in-stock price.
		if ((view.retailer || view.inStock) && price === null) return false;
		if (view.max !== null && (price === null || price > view.max)) return false;
		return true;
	});
	const key = view.sort;
	if (!key) return kept;
	const sign = view.dir === 'desc' ? -1 : 1;
	return kept.sort((a, b) => {
		const va = sortValue(a, key, view);
		const vb = sortValue(b, key, view);
		if (va === null && vb !== null) return 1;
		if (vb === null && va !== null) return -1;
		if (va !== null && vb !== null) {
			const c = cmp(va, vb) * sign;
			if (c) return c;
		}
		return cmp(a.model, b.model) || a.productId - b.productId;
	});
}

export function activeFilterCount(view: CatalogView): number {
	return (
		(view.max !== null ? 1 : 0) +
		(view.brands.length ? 1 : 0) +
		(view.gens.length ? 1 : 0) +
		(view.inStock ? 1 : 0) +
		(view.retailer ? 1 : 0)
	);
}

// The retailer picker offers only the retailers the pipeline still scrapes
// (config.ACTIVE_RETAILERS). The parser accepts all six slugs so an old link
// still parses; it just narrows to a retailer with no current prices.
const ACTIVE_RETAILERS: readonly Retailer[] = ['scorptec', 'pccg', 'umart'];
export const ACTIVE_RETAILER_OPTIONS = RETAILER_OPTIONS.filter((o) => ACTIVE_RETAILERS.includes(o.value));

export const CATALOG_BRANDS: readonly string[] = BRANDS;

interface GenSource {
	brand: string;
	category: string;
	generationTier: GenerationTier | null;
}

// One option per tier present, labelled by the series it holds in this
// category ("RTX 50 / RX 9000"): "current-1" means nothing to a buyer.
export function genOptions(rows: GenSource[]): { value: GenerationTier; label: string }[] {
	const out: { value: GenerationTier; label: string }[] = [];
	for (const tier of GENS as GenerationTier[]) {
		const inTier = rows.filter((r) => r.generationTier === tier);
		if (!inTier.length) continue;
		const names: string[] = [];
		for (const brand of BRANDS) {
			const r = inTier.find((x) => x.brand === brand);
			const label = r ? generationTierLabel(r.brand, r.category, tier) : null;
			const short = label?.replace(/\s*\(.*\)$/, '');
			if (short && !names.includes(short)) names.push(short);
		}
		out.push({ value: tier, label: names.join(' / ') });
	}
	return out;
}

// The earliest release year in a series group: its launch year.
export function earliestYear(items: { releaseYear?: number | null }[]): number | null {
	let min: number | null = null;
	for (const i of items) {
		if (i.releaseYear != null && (min === null || i.releaseYear < min)) min = i.releaseYear;
	}
	return min;
}
