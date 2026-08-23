// Offer-list logic for the product page: ordering, facets and volume control.
// Kept separate from productHeadline.ts — this answers "which offers do we
// show", that one answers "is this price any good".
import type { ListingDisplay } from './listingsPanel';
import { RETAILER_OPTIONS } from './filters';

export type { ListingDisplay };

export type OfferTier = 'in_stock' | 'out_of_stock' | 'delisted';

const TIER_ORDER: Record<OfferTier, number> = {
	in_stock: 0,
	out_of_stock: 1,
	delisted: 2
};

export function offerTier(o: ListingDisplay): OfferTier {
	if (o.delisted) return 'delisted';
	return o.inStock ? 'in_stock' : 'out_of_stock';
}

// Cheapest in-stock first. Tiers never interleave: an out-of-stock $999 above
// an in-stock $1,099 would misrepresent what is actually buyable.
export function sortOffers(offers: ListingDisplay[]): ListingDisplay[] {
	return [...offers].sort((a, b) => {
		const tier = TIER_ORDER[offerTier(a)] - TIER_ORDER[offerTier(b)];
		if (tier !== 0) return tier;
		if (a.latestPrice === null && b.latestPrice === null) return 0;
		if (a.latestPrice === null) return 1;
		if (b.latestPrice === null) return -1;
		return a.latestPrice - b.latestPrice;
	});
}

export interface FacetOption {
	value: string;
	label: string;
	count: number;
}

const RETAILER_LABELS = new Map(RETAILER_OPTIONS.map((o) => [o.value as string, o.label]));

// Brand is already a display string (derived by deriveListingBrand); retailer
// is a slug that needs its label. An unknown slug falls back to itself so a
// newly-added retailer shows up rather than rendering blank.
function facetLabel(key: 'retailer' | 'brand', value: string): string {
	if (key === 'brand') return value;
	return RETAILER_LABELS.get(value) ?? value;
}

export function facetCounts(
	offers: ListingDisplay[],
	key: 'retailer' | 'brand'
): FacetOption[] {
	const counts = new Map<string, number>();
	for (const o of offers) {
		const value = o[key];
		counts.set(value, (counts.get(value) ?? 0) + 1);
	}
	return [...counts.entries()]
		.map(([value, count]) => ({ value, label: facetLabel(key, value), count }))
		.sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

// Flattening the accordions removed repetition but not volume: 50 listings is
// still 50 rows. These two defaults are what actually shorten the page.
export const OFFER_PAGE_SIZE = 8;

export interface OfferFilters {
	inStockOnly: boolean;
	retailer: string | null;
	brand: string | null;
	query: string;
}

export interface OfferView {
	visible: ListingDisplay[];
	// Offers matching the active filters (the expander's total).
	matched: number;
	// Offers before any filtering (the "of 31" in "18 of 31").
	total: number;
	inStockCount: number;
	showExpander: boolean;
	// Whether the stock filter actually ran. False when forced off.
	stockFilterApplied: boolean;
	// The product has no in-stock offers at all, so the stock filter was
	// ignored to avoid rendering an empty page for a product that has prices.
	stockFilterForcedOff: boolean;
}

export function buildOfferView(
	offers: ListingDisplay[],
	filters: OfferFilters,
	expanded: boolean
): OfferView {
	const total = offers.length;
	const inStockCount = offers.filter((o) => o.inStock).length;

	const stockFilterForcedOff = filters.inStockOnly && inStockCount === 0 && total > 0;
	const stockFilterApplied = filters.inStockOnly && !stockFilterForcedOff;

	const q = filters.query.trim().toLowerCase();
	// Filter first, then sort, then cap. This order is contractual: filtering
	// before capping ensures the expander's total matches the filtered set, so
	// the "N of M" label never contradicts the expander state. On the stock
	// axis, this ordering is further reinforced by offerTier sorting all
	// in-stock rows ahead of out-of-stock rows, making cap-then-filter
	// mathematically indistinguishable. The retailer-facet test discriminates
	// the two approaches (cap-then-filter would leave ~4 rows after filtering
	// the cap's mix to a single retailer); that test is the one that actually
	// pins the ordering.
	const matchedOffers = offers.filter((o) => {
		if (stockFilterApplied && !o.inStock) return false;
		if (filters.retailer && o.retailer !== filters.retailer) return false;
		if (filters.brand && o.brand !== filters.brand) return false;
		if (q) {
			const haystack = `${o.variantName ?? ''} ${o.retailer}`.toLowerCase();
			if (!haystack.includes(q)) return false;
		}
		return true;
	});

	const sorted = sortOffers(matchedOffers);
	return {
		visible: expanded ? sorted : sorted.slice(0, OFFER_PAGE_SIZE),
		matched: sorted.length,
		total,
		inStockCount,
		showExpander: sorted.length > OFFER_PAGE_SIZE,
		stockFilterApplied,
		stockFilterForcedOff
	};
}
