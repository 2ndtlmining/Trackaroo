import {
	getLatestListings,
	getProductDealStats,
	getTrackedProducts,
	groupListingsByProduct
} from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { memo } from '$lib/server/cache';
import { parseFilters } from '$lib/filters';
import type { Category, ListingFilters } from '$lib/types';

// The index ships the whole category to the browser and filters there, so this
// load deliberately does less than it used to: no text search, no sort, no
// per-listing or per-product sparkline queries, no facet counts. ~50 rows is a
// few kilobytes, which it now actually is: groups drop their per-listing
// arrays (#28), since nothing on this page reads a group's `listings`.
export function load({
	url,
	setHeaders
}: {
	url: URL;
	setHeaders: (headers: Record<string, string>) => void;
}) {
	const db = getDb();
	const parsed: ListingFilters = parseFilters(url.searchParams);
	// Category is the page (the GPUs / CPUs nav destinations), so it always has
	// a subject even when the URL omits one.
	const category: Category = parsed.category ?? 'gpu';
	// "In stock" must still narrow the page. Watchlist-only products have no
	// stock by definition, so they drop out when the filter is on.
	const inStockOnly = parsed.inStock ?? false;
	setHeaders({ 'cache-control': 'public, max-age=60, stale-while-revalidate=300' });

	const { trackedCount, listedCount, groups: visible } = memo(
		db,
		`products:${category}:${inStockOnly}`,
		() => {
			const listings = getLatestListings(db, { category, inStock: parsed.inStock });
			const withListings = groupListingsByProduct(listings);
			const dealStats = getProductDealStats(db, withListings.map((g) => g.productId));
			const byProduct = new Map(withListings.map((g) => [g.productId, g]));

			// Start from the watchlist, not from what has been scraped. Around 39%
			// of tracked products have never matched a listing; dropping them would
			// make a search for a genuinely tracked model answer "no match", which
			// is a different claim from "nobody stocks it".
			const groups = getTrackedProducts(db, category).map((product) => {
				const group = byProduct.get(product.productId);
				if (!group) {
					return {
						...product,
						cheapestInStockPrice: null,
						cheapestInStockRetailer: null,
						inStockCount: 0,
						avg30: null,
						avg30Points: 0,
						neverListed: true
					};
				}
				const stats = dealStats.get(group.productId);
				const { listings: _listings, ...rest } = group;
				return {
					...rest,
					avg30: stats?.avg30 ?? null,
					avg30Points: stats?.avg30Points ?? 0,
					neverListed: false
				};
			});

			const visible = inStockOnly ? groups.filter((g) => g.cheapestInStockPrice !== null) : groups;

			return {
				// Always the whole category, so the header does not restate the
				// filtered count back as though it were the catalogue size.
				trackedCount: groups.length,
				listedCount: withListings.length,
				groups: visible
			};
		}
	);

	return {
		category,
		inStockOnly,
		trackedCount,
		listedCount,
		groups: visible
	};
}
