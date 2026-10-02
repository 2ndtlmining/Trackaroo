import { describe, expect, it } from 'vitest';
import {
	ACTIVE_RETAILER_OPTIONS, activeFilterCount, applyCatalogView, brandOptions, catalogViewParams, earliestYear, genOptions,
	parseCatalogView, shownPrice, shownStock,
	type CatalogRowInput
} from '../src/lib/catalogView';

const p = (q: string) => parseCatalogView(new URLSearchParams(q));
const row = (o: Partial<CatalogRowInput> & { productId: number }): CatalogRowInput => ({
	brand: 'NVIDIA', model: `M${o.productId}`, generationTier: 'current', cheapestInStockPrice: null,
	retailerPrices: {}, vramGb: null, cores: null, launchDate: null, listingCount: 0, neverListed: false, ...o
});

describe('parseCatalogView', () => {
	it('defaults', () => {
		expect(p('')).toEqual({ max: null, brands: [], gens: [], inStock: false, retailer: null, sort: null, dir: 'asc' });
	});
	it('reads every param, repeatable and comma lists, canonical brand case', () => {
		const v = p('max=1000&brand=nvidia,AMD&brand=Intel&gen=current&gen=current-1&in_stock=1&retailer=pccg&sort=price&dir=desc');
		expect(v).toEqual({ max: 1000, brands: ['NVIDIA', 'AMD', 'Intel'], gens: ['current', 'current-1'], inStock: true, retailer: 'pccg', sort: 'price', dir: 'desc' });
	});
	it('drops invalid values instead of failing', () => {
		expect(p('max=abc&brand=Foo&gen=old&retailer=amazon&sort=bogus&dir=up&in_stock=yes')).toEqual(p(''));
		expect(p('max=-5').max).toBeNull();
		expect(p('max=0').max).toBeNull();
		expect(p('max=1e9').max).toBeNull(); // only plain positive integers up to 100000
	});
	it('accepts in_stock=true as well as 1, like parseFilters (final review #4)', () => {
		expect(p('in_stock=true').inStock).toBe(true);
		expect(p('in_stock=1').inStock).toBe(true);
		expect(p('in_stock=TRUE').inStock).toBe(false);
		expect(p('in_stock=0').inStock).toBe(false);
	});
	it('sort without dir uses the key default', () => {
		expect(p('sort=spec').dir).toBe('desc');
		expect(p('sort=released').dir).toBe('desc');
		expect(p('sort=name').dir).toBe('asc');
	});
});

describe('catalogViewParams round-trip', () => {
	it('serialises only non-default values', () => {
		expect(catalogViewParams(p(''))).toEqual({ max: null, brand: null, gen: null, in_stock: null, retailer: null, sort: null, dir: null });
		const v = p('max=500&brand=AMD&gen=current&in_stock=1&retailer=umart&sort=price&dir=desc');
		const back = new URLSearchParams(Object.entries(catalogViewParams(v)).filter(([, x]) => x !== null) as [string, string][]);
		expect(parseCatalogView(back)).toEqual(v);
	});
	it('omits dir when it equals the key default', () => {
		expect(catalogViewParams(p('sort=price&dir=asc')).dir).toBeNull();
	});
});

describe('shownPrice', () => {
	const r = row({ productId: 1, cheapestInStockPrice: 900, retailerPrices: { pccg: { inStock: null, any: 850 }, umart: { inStock: 950, any: 950 } } });
	it('is the overall cheapest in stock without a retailer', () => expect(shownPrice(r, p(''))).toBe(900));
	it("is the retailer's cheapest of any stock without in_stock", () => expect(shownPrice(r, p('retailer=pccg'))).toBe(850));
	it("is the retailer's cheapest in stock with in_stock", () => {
		expect(shownPrice(r, p('retailer=pccg&in_stock=1'))).toBeNull();
		expect(shownPrice(r, p('retailer=umart&in_stock=1'))).toBe(950);
	});
	it('is null for a retailer that does not list it', () => expect(shownPrice(r, p('retailer=scorptec'))).toBeNull());
});

describe('shownStock (final review #1)', () => {
	const r = row({ productId: 1, cheapestInStockPrice: 900, retailerPrices: { pccg: { inStock: null, any: 850 }, umart: { inStock: 950, any: 950 } } });
	it('is in for the overall cheapest in stock', () => expect(shownStock(r, p(''))).toBe('in'));
	it('is null when nothing is in stock anywhere and no retailer is chosen', () =>
		expect(shownStock(row({ productId: 2 }), p(''))).toBeNull());
	it("is out when the retailer's only price is out of stock", () => expect(shownStock(r, p('retailer=pccg'))).toBe('out'));
	it('is in when the retailer has it in stock', () => expect(shownStock(r, p('retailer=umart'))).toBe('in'));
	it('is null for a retailer that does not list it', () => expect(shownStock(r, p('retailer=scorptec'))).toBeNull());
	it('is null with in_stock on and no in-stock price there (no price is shown)', () =>
		expect(shownStock(r, p('retailer=pccg&in_stock=1'))).toBeNull());
});

describe('applyCatalogView', () => {
	const rows = [
		row({ productId: 1, brand: 'NVIDIA', cheapestInStockPrice: 1200, vramGb: 16, launchDate: '2025-01-30', listingCount: 9, retailerPrices: { pccg: { inStock: 1200, any: 1200 } } }),
		row({ productId: 2, brand: 'AMD', generationTier: 'current-1', cheapestInStockPrice: 600, vramGb: 16, launchDate: '2024-01-24', listingCount: 3, retailerPrices: { umart: { inStock: 600, any: 600 } } }),
		row({ productId: 3, brand: 'Intel', cheapestInStockPrice: 400, vramGb: 12, launchDate: '2024-12-12', listingCount: 5, retailerPrices: { pccg: { inStock: null, any: 380 } } }),
		row({ productId: 4, brand: 'NVIDIA', neverListed: true, vramGb: 8, launchDate: null })
	];
	const ids = (q: string) => applyCatalogView(rows, p(q)).map((r) => r.productId);

	it('no view: unchanged order', () => expect(ids('')).toEqual([1, 2, 3, 4]));
	it('max hides pricier and unpriced', () => expect(ids('max=700')).toEqual([2, 3]));
	it('brand and gen', () => {
		expect(ids('brand=NVIDIA')).toEqual([1, 4]);
		expect(ids('gen=current-1')).toEqual([2]);
		expect(ids('brand=NVIDIA,Intel&gen=current')).toEqual([1, 3, 4]);
	});
	it('in_stock hides products without an in-stock price', () => expect(ids('in_stock=1')).toEqual([1, 2, 3]));
	it('retailer keeps only products listed there', () => {
		expect(ids('retailer=pccg')).toEqual([1, 3]);
		expect(ids('retailer=pccg&in_stock=1')).toEqual([1]);
		expect(ids('retailer=pccg&max=500')).toEqual([3]); // 380 at pccg (any stock)
	});
	it('price sort puts unpriced last in both directions', () => {
		expect(ids('sort=price')).toEqual([3, 2, 1, 4]);
		expect(ids('sort=price&dir=desc')).toEqual([1, 2, 3, 4]);
	});
	it('other sorts, ties broken by name then id', () => {
		expect(ids('sort=spec')).toEqual([1, 2, 3, 4]);           // vram desc
		expect(ids('sort=released')).toEqual([1, 3, 2, 4]);       // newest first, unknown last
		expect(ids('sort=listings')).toEqual([1, 3, 2, 4]);
		expect(ids('sort=name&dir=desc')).toEqual([4, 3, 2, 1]);
	});
	it('spec sorts CPUs by cores', () => {
		const cpus = [row({ productId: 1, cores: 6 }), row({ productId: 2, cores: 16 }), row({ productId: 3, cores: 8 })];
		expect(applyCatalogView(cpus, p('sort=spec')).map((r) => r.productId)).toEqual([2, 3, 1]);
	});
	it('counts active filters (not sort)', () => {
		// brand counts once however many brands are ticked; sort is not a filter
		expect(activeFilterCount(p('max=500&brand=AMD,Intel&in_stock=1&sort=price'))).toBe(3);
	});
});

describe('catalogue control helpers (#23)', () => {
	it('genOptions labels each tier present by its short series names, newest first', () => {
		const rows = [
			{ brand: 'AMD', category: 'gpu', generationTier: 'current-1' as const },
			{ brand: 'NVIDIA', category: 'gpu', generationTier: 'current' as const },
			{ brand: 'Intel', category: 'gpu', generationTier: 'current' as const },
			{ brand: 'NVIDIA', category: 'gpu', generationTier: 'current' as const },
			{ brand: 'NVIDIA', category: 'gpu', generationTier: null }
		];
		expect(genOptions(rows)).toEqual([
			{ value: 'current', label: 'RTX 50 / Arc B' },
			{ value: 'current-1', label: 'RX 7000' }
		]);
	});
	it('genOptions uses the CPU series names', () => {
		expect(genOptions([{ brand: 'AMD', category: 'cpu', generationTier: 'current-2' as const }])).toEqual([
			{ value: 'current-2', label: 'Ryzen 5000' }
		]);
	});
	it('genOptions keeps a selected tier no row has, with its generic label (final review #6)', () => {
		const rows = [{ brand: 'NVIDIA', category: 'gpu', generationTier: 'current' as const }];
		expect(genOptions(rows, ['current-2'])).toEqual([
			{ value: 'current', label: 'RTX 50' },
			{ value: 'current-2', label: 'Two gens back' }
		]);
		expect(genOptions(rows, ['current'])).toEqual([{ value: 'current', label: 'RTX 50' }]);
	});
	it('brandOptions lists brands present plus any selected, in canonical order (final review #6)', () => {
		const rows = [{ brand: 'Intel' }, { brand: 'AMD' }];
		expect(brandOptions(rows, [])).toEqual(['AMD', 'Intel']);
		expect(brandOptions(rows, ['NVIDIA'])).toEqual(['NVIDIA', 'AMD', 'Intel']);
		expect(brandOptions([], ['AMD'])).toEqual(['AMD']);
	});
	it('earliestYear is the smallest release year, null when none', () => {
		expect(earliestYear([{ releaseYear: 2025 }, { releaseYear: null }, { releaseYear: 2024 }])).toBe(2024);
		expect(earliestYear([{ releaseYear: null }, {}])).toBeNull();
	});
	it('the retailer picker offers only the active retailers', () => {
		expect(ACTIVE_RETAILER_OPTIONS.map((o) => o.value)).toEqual(['scorptec', 'pccg', 'umart']);
	});
});
