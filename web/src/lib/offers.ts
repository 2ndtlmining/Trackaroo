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
