import { getBrands, getLatestListings } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { parseFilters } from '$lib/filters';
import type { ListingFilters } from '$lib/types';

export function load({ url }: { url: URL }) {
	const db = getDb();
	const filters: ListingFilters = parseFilters(url.searchParams);
	return {
		listings: getLatestListings(db, filters),
		brands: getBrands(db)
	};
}