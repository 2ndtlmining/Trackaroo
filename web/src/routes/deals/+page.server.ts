import { getDealCandidates } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { memo } from '$lib/server/cache';
import {
	atAllTimeLow,
	belowAverage,
	categoryFacetCounts,
	filterDeals,
	shownDeals,
	toDeals,
	type DealFilters
} from '$lib/deals';
import { facetCounts } from '$lib/offers';

function param(url: URL, key: string): string | null {
	const value = url.searchParams.get(key);
	return value && value.trim() !== '' ? value : null;
}

export function load({
	url,
	setHeaders
}: {
	url: URL;
	setHeaders: (headers: Record<string, string>) => void;
}) {
	const db = getDb();
	setHeaders({ 'cache-control': 'public, max-age=60, stale-while-revalidate=300' });
	// Same key as the home page, so a request from either route shares one
	// cached scan instead of each paying for its own (#28).
	const candidates = memo(db, 'dealCandidates', () => getDealCandidates(db));
	// Facets count the rows the page can actually show, so "All 42" can't sit
	// above 32 rows (28-Sep finding).
	const deals = shownDeals(toDeals(candidates));

	// Earliest history across all candidates, not just the shown ones, so the
	// subtitle states the true depth of "all-time" even when the deepest
	// history belongs to a product with no current deal.
	const historyStart = candidates.reduce<string | null>((earliest, c) => {
		if (c.historyStart === null) return earliest;
		return earliest === null || c.historyStart < earliest ? c.historyStart : earliest;
	}, null);

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
		eligibleCount: deals.length,
		historyStart
	};
}
