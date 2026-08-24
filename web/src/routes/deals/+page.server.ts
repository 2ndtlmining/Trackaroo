import { getDealCandidates } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import {
	atAllTimeLow,
	belowAverage,
	categoryFacetCounts,
	filterDeals,
	toDeals,
	type DealFilters
} from '$lib/deals';
import { facetCounts } from '$lib/offers';

function param(url: URL, key: string): string | null {
	const value = url.searchParams.get(key);
	return value && value.trim() !== '' ? value : null;
}

export function load({ url }: { url: URL }) {
	const db = getDb();
	const deals = toDeals(getDealCandidates(db));

	const filters: DealFilters = {
		category: param(url, 'category'),
		retailer: param(url, 'retailer'),
		brand: param(url, 'brand')
	};

	// Each axis is counted over the set filtered by the OTHER axes, so a
	// chip's count always equals the number of rows clicking it produces.
	const forCategory = filterDeals(deals, { ...filters, category: null });
	const forRetailer = filterDeals(deals, { ...filters, retailer: null });
	const forBrand = filterDeals(deals, { ...filters, brand: null });

	const visible = filterDeals(deals, filters);

	return {
		belowAverage: belowAverage(visible),
		atAllTimeLow: atAllTimeLow(visible),
		filters,
		facets: {
			category: categoryFacetCounts(forCategory),
			retailer: facetCounts(forRetailer, 'retailer'),
			brand: facetCounts(forBrand, 'brand')
		},
		totals: {
			category: forCategory.length,
			retailer: forRetailer.length,
			brand: forBrand.length
		},
		eligibleCount: deals.length
	};
}
