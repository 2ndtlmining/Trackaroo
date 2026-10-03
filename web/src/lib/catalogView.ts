import { RETAILER_OPTIONS, TIER_OPTIONS } from './filters';
import type { FxRate } from './models';
import { msrpAud, msrpDelta } from './msrp';
import { perfPerKilo } from './value';
import { generationTierLabel } from './tiers';
import type { GenerationTier, Retailer } from './types';

export type CatalogSort = 'price' | 'name' | 'spec' | 'released' | 'listings' | 'msrp' | 'value';
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
	msrpUsd: number | null;
	listingCount: number;
	neverListed: boolean;
	// Index performance for the category's metric (#33); absent or null = no figure.
	perf?: number | null;
}

export const DEFAULT_DIR: Record<CatalogSort, SortDir> = {
	price: 'asc',
	name: 'asc',
	spec: 'desc',
	released: 'desc',
	listings: 'desc',
	msrp: 'asc',
	value: 'desc'
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

	// '1' or 'true', exactly as parseFilters reads it for the server's load.
	const inStockRaw = params.get('in_stock');
	const inStock = inStockRaw === '1' || inStockRaw === 'true';

	return { max, brands, gens, inStock, retailer, sort, dir };
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
	// Without in_stock, show the buyable price when there is one: a cheaper
	// sold-out listing must not pose as a deal. Fall back to the sold-out
	// price (shownStock says 'out', so it is labelled) only when nothing is.
	return view.inStock ? entry.inStock : (entry.inStock ?? entry.any);
}

// Whether the shown price is an in-stock one. 'out' only in a retailer view
// with in_stock off, when that retailer lists the product but has none in
// stock: the row then shows its any-stock price and must say so (no deal cue).
export function shownStock(row: CatalogRowInput, view: CatalogView): 'in' | 'out' | null {
	if (!view.retailer) return row.cheapestInStockPrice !== null ? 'in' : null;
	const entry = row.retailerPrices[view.retailer];
	if (!entry) return null;
	if (entry.inStock !== null) return 'in';
	return !view.inStock && entry.any !== null ? 'out' : null;
}

// Context the view itself cannot carry: the AUD/USD rate for sort=msrp.
export interface CatalogContext {
	fx: FxRate | null;
}

function sortValue(
	row: CatalogRowInput,
	key: CatalogSort,
	view: CatalogView,
	ctx: CatalogContext
): number | string | null {
	switch (key) {
		case 'price': return shownPrice(row, view);
		case 'name': return row.model;
		case 'spec': return row.vramGb ?? row.cores;
		case 'released': return row.launchDate;
		case 'listings': return row.listingCount;
		// R7: an out-of-stock shown price has no figure, so it sorts last.
		case 'value': return shownStock(row, view) === 'out' ? null : perfPerKilo(shownPrice(row, view), row.perf ?? null);
		case 'msrp': return msrpDelta(shownPrice(row, view), msrpAud(row.msrpUsd, ctx.fx));
	}
}

const cmp = (a: number | string, b: number | string) => (a < b ? -1 : a > b ? 1 : 0);

export function applyCatalogView<T extends CatalogRowInput>(
	rows: T[],
	view: CatalogView,
	ctx: CatalogContext = { fx: null }
): T[] {
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
		const va = sortValue(a, key, view, ctx);
		const vb = sortValue(b, key, view, ctx);
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
// KEEP IN STEP with ACTIVE_RETAILERS in config.py (repo root): when a
// retailer is added or retired there, change this list too.
const ACTIVE_RETAILERS: readonly Retailer[] = ['scorptec', 'pccg', 'umart'];
export const ACTIVE_RETAILER_OPTIONS = RETAILER_OPTIONS.filter((o) => ACTIVE_RETAILERS.includes(o.value));

export const CATALOG_BRANDS: readonly string[] = BRANDS;

// The brands present in these rows plus any selected one, in canonical order:
// like genOptions, a ticked brand keeps its checkbox even with no rows.
export function brandOptions(rows: { brand: string }[], selected: readonly string[]): string[] {
	return BRANDS.filter((b) => selected.includes(b) || rows.some((r) => r.brand === b));
}

interface GenSource {
	brand: string;
	category: string;
	generationTier: GenerationTier | null;
}

// One option per tier present, labelled by the series it holds in this
// category ("RTX 50 / RX 9000"): "current-1" means nothing to a buyer.
// A tier in `selected` that no row has still gets an option (with its generic
// label), so an active filter never loses its control (the server's in_stock
// narrowing can leave a selected tier with no rows).
export function genOptions(
	rows: GenSource[],
	selected: readonly GenerationTier[] = []
): { value: GenerationTier; label: string }[] {
	const out: { value: GenerationTier; label: string }[] = [];
	for (const tier of GENS as GenerationTier[]) {
		const inTier = rows.filter((r) => r.generationTier === tier);
		if (!inTier.length) {
			if (selected.includes(tier)) {
				out.push({ value: tier, label: TIER_OPTIONS.find((o) => o.value === tier)?.label ?? tier });
			}
			continue;
		}
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
