import {
	getBrands,
	getLatestListings,
	getProductSparklines,
	getSparklines,
	groupListingsByProduct
} from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { parseFilters } from '$lib/filters';
import type { ListingFilters } from '$lib/types';

export function load({ url }: { url: URL }) {
	const db = getDb();
	const filters: ListingFilters = parseFilters(url.searchParams);
	const listings = getLatestListings(db, filters);
	const sparklines = getSparklines(db, listings.map((l) => l.listingId));
	const withSparklines = listings.map((l) => ({
		...l,
		sparkline: sparklines.get(l.listingId) ?? []
	}));
	const groups = groupListingsByProduct(withSparklines, filters.sort);
	const productSparklines = getProductSparklines(db, groups.map((g) => g.productId));
	return {
		groups: groups.map((g) => ({
			...g,
			sparkline: productSparklines.get(g.productId) ?? []
		})),
		brands: getBrands(db)
	};
}
