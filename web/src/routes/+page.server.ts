import { getBrands, getCheapestPerModel, getLatestListings, getSparklines, getSummary } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { parseFilters } from '$lib/filters';
import type { ListingFilters } from '$lib/types';

export function load({ url }: { url: URL }) {
	const db = getDb();
	const filters: ListingFilters = parseFilters(url.searchParams);
	const listings = getLatestListings(db, filters);
	const sparklines = getSparklines(db, listings.map((l) => l.listingId));
	return {
		summary: getSummary(db),
		listings: listings.map((l) => ({ ...l, sparkline: sparklines.get(l.listingId) ?? [] })),
		brands: getBrands(db),
		cheapestGpu: getCheapestPerModel(db, 'gpu'),
		cheapestCpu: getCheapestPerModel(db, 'cpu')
	};
}