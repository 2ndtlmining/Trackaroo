import { getBrands, getLatestListings, groupListingsByProduct } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { parseFilters } from '$lib/filters';
import type { ListingFilters } from '$lib/types';

export function load({ url }: { url: URL }) {
	const db = getDb();
	const filters: ListingFilters = parseFilters(url.searchParams);
	return {
		groups: groupListingsByProduct(getLatestListings(db, filters), filters.sort),
		brands: getBrands(db)
	};
}
