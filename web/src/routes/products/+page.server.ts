import {
	getBrands,
	getLatestListings,
	getProductDealStats,
	getProductSparklines,
	getSparklines,
	groupListingsByProduct
} from '$lib/server/repos';
import { MIN_HISTORY_POINTS } from '$lib/constants';
import { getDb } from '$lib/server/db';
import { parseFilters } from '$lib/filters';
import { facetCounts } from '$lib/offers';
import type { ListingFilters } from '$lib/types';

export function load({ url }: { url: URL }) {
	const db = getDb();
	const filters: ListingFilters = parseFilters(url.searchParams);
	// Counted over the set filtered by every axis EXCEPT retailer, so a chip's
	// count always equals the number of rows clicking it produces.
	const forCounts = getLatestListings(db, { ...filters, retailer: undefined });
	const retailerFacets = facetCounts(forCounts, 'retailer');
	const listings = filters.retailer
		? forCounts.filter((l) => l.retailer === filters.retailer)
		: forCounts;
	const sparklines = getSparklines(db, listings.map((l) => l.listingId));
	const withSparklines = listings.map((l) => ({
		...l,
		sparkline: sparklines.get(l.listingId) ?? []
	}));
	const groups = groupListingsByProduct(withSparklines, filters.sort);
	const productSparklines = getProductSparklines(db, groups.map((g) => g.productId));
	const dealStats = getProductDealStats(db, groups.map((g) => g.productId));
	return {
		groups: groups.map((g) => {
			const stats = dealStats.get(g.productId);
			const avg30 = stats?.avg30 ?? null;
			return {
				...g,
				sparkline: productSparklines.get(g.productId) ?? [],
				avg30,
				avg30Points: stats?.avg30Points ?? 0,
				// A deal is the current cheapest in-stock price sitting below
				// the 30-day average, only when there's enough history to
				// trust the average (avoids flagging 1-2 day products).
				deal:
					g.cheapestInStockPrice !== null &&
					avg30 !== null &&
					(stats?.avg30Points ?? 0) >= MIN_HISTORY_POINTS &&
					g.cheapestInStockPrice < avg30
			};
		}),
		brands: getBrands(db),
		retailerFacets,
		retailerTotal: forCounts.length
	};
}
