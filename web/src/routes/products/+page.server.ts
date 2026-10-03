import {
	getCpuSpecs,
	getLatestListings,
	getLatestFxRate,
	getLaunchDates,
	getLaunchMsrps,
	getProductDealStats,
	getProductSparklines,
	getTrackedProducts,
	groupListingsByProduct
} from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { memo } from '$lib/server/cache';
import { parseFilters } from '$lib/filters';
import type { Category, ListingFilters, Retailer } from '$lib/types';
import type { LatestListing } from '$lib/models';

type RetailerPrices = Partial<Record<Retailer, { inStock: number | null; any: number | null }>>;

// Cheapest latest price per retailer, overall and in stock. Computed from the
// whole listing set, never the in-stock-filtered one, so `any` stays honest.
function retailerPricesOf(listings: LatestListing[]): RetailerPrices {
	const out: RetailerPrices = {};
	for (const l of listings) {
		const cell = (out[l.retailer] ??= { inStock: null, any: null });
		if (cell.any === null || l.latestPrice < cell.any) cell.any = l.latestPrice;
		if (l.latestStock === 'in_stock' && (cell.inStock === null || l.latestPrice < cell.inStock)) {
			cell.inStock = l.latestPrice;
		}
	}
	return out;
}

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

	// The memo is per category only: the listings are fetched unfiltered so
	// retailerPrices.any and listingCount do not shrink when "in stock" is on;
	// the in-stock narrowing happens after the memo.
	const base = memo(
		db,
		`products:${category}`,
		() => {
			const listings = getLatestListings(db, { category });
			const withListings = groupListingsByProduct(listings);
			const dealStats = getProductDealStats(db, withListings.map((g) => g.productId));
			const byProduct = new Map(withListings.map((g) => [g.productId, g]));
			const launchDates = getLaunchDates(db, category);
			const cpuSpecs = getCpuSpecs(db, category);
			const msrps = getLaunchMsrps(db, category);
			const sparklines = getProductSparklines(db, category, 30);
			const extras = (productId: number, launchDate: string | null) => ({
				sparkline: (sparklines.get(productId) ?? []).map((p) => p.price),
				msrpUsd: msrps.get(productId) ?? null,
				socket: cpuSpecs.get(productId)?.socket ?? null,
				threads: cpuSpecs.get(productId)?.threads ?? null,
				releaseYear: launchDate ? Number(launchDate.slice(0, 4)) : null
			});

			// Start from the watchlist, not from what has been scraped. Around 39%
			// of tracked products have never matched a listing; dropping them would
			// make a search for a genuinely tracked model answer "no match", which
			// is a different claim from "nobody stocks it".
			const groups = getTrackedProducts(db, category).map((product) => {
				const group = byProduct.get(product.productId);
				const launchDate = launchDates.get(product.productId) ?? null;
				if (!group) {
					return {
						...product,
						launchDate,
						...extras(product.productId, launchDate),
						retailerPrices: {} as RetailerPrices,
						listingCount: 0,
						cheapestInStockPrice: null,
						cheapestInStockRetailer: null,
						inStockCount: 0,
						avg30: null,
						avg30Points: 0,
						neverListed: true
					};
				}
				const stats = dealStats.get(group.productId);
				const { listings, ...rest } = group;
				return {
					...rest,
					...extras(group.productId, launchDate),
					retailerPrices: retailerPricesOf(listings),
					vramGb: product.vramGb,
					cores: product.cores,
					launchDate,
					// Active listings (in stock or not): the "of N" in "3 of 5".
					listingCount: listings.length,
					avg30: stats?.avg30 ?? null,
					avg30Points: stats?.avg30Points ?? 0,
					neverListed: false
				};
			});

			return {
				trackedCount: groups.length,
				listedCount: withListings.length,
				listedInStockCount: withListings.filter((g) => g.inStockCount > 0).length,
				groups
			};
		}
	);
	const visible = inStockOnly ? base.groups.filter((g) => g.cheapestInStockPrice !== null) : base.groups;
	// Always the whole category, so the header does not restate the filtered
	// count back as though it were the catalogue size.
	const trackedCount = base.trackedCount;
	const listedCount = inStockOnly ? base.listedInStockCount : base.listedCount;

	return {
		wide: true,
		category,
		inStockOnly,
		trackedCount,
		listedCount,
		fx: getLatestFxRate(db),
		groups: visible
	};
}
