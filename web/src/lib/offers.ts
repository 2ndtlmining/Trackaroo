// Offer-list logic for the product page: ordering, facets and volume control.
// Kept separate from productHeadline.ts — this answers "which offers do we
// show", that one answers "is this price any good".
import type { ListingDisplay } from './listingsPanel';

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
