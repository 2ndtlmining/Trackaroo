// Deal ranking for /deals. Pure — no DB access — so every rule here is
// unit-testable. Answers two different questions that must not be blended:
// "is this cheap versus its own recent history" (below the 30-day average)
// and "is this cheap versus all history" (at or near the all-time low).
import { MIN_HISTORY_POINTS } from './constants';
import { CATEGORY_OPTIONS } from './filters';
import type { FacetOption } from './offers';
import type { ListingDisplay } from './listingsPanel';
import type { DealCandidate } from './server/repos';

export type { DealCandidate };

// "Near" the all-time low, per the spec. A stronger claim than below-average,
// so it gets its own section rather than being folded into one score.
export const NEAR_ALL_TIME_LOW_PCT = 2;

export interface Deal extends DealCandidate {
	// Percent below the 30-day average. Positive = cheaper than average.
	depthPct: number | null;
	nearAllTimeLow: boolean;
}

export interface DealFilters {
	category: string | null;
	retailer: string | null;
	brand: string | null;
}

// A three-day average is not an average. Gating on it keeps a product that has
// barely been tracked from being presented as a bargain — and the same depth
// requirement guards the all-time-low claim, which is no more meaningful over
// three days than the average is.
export function isEligible(c: DealCandidate): boolean {
	return c.avg30 !== null && c.avg30 !== 0 && c.avg30Points >= MIN_HISTORY_POINTS;
}

// Positive means below the average. Note the sign is inverted relative to
// offers.deltaVsAvg30, which is a *delta* (negative = cheaper); this is a
// *depth* (positive = cheaper) because it is a ranking key, and ranking
// "deepest first" reads backwards on a negative scale.
export function dealDepthPct(price: number, avg30: number | null): number | null {
	if (avg30 === null || avg30 === 0) return null;
	return ((avg30 - price) / avg30) * 100;
}

export function isNearAllTimeLow(price: number, allTimeLow: number | null): boolean {
	if (allTimeLow === null || allTimeLow === 0) return false;
	return price <= allTimeLow * (1 + NEAR_ALL_TIME_LOW_PCT / 100);
}

export function toDeals(candidates: DealCandidate[]): Deal[] {
	return candidates.filter(isEligible).map((c) => ({
		...c,
		depthPct: dealDepthPct(c.price, c.avg30),
		nearAllTimeLow: isNearAllTimeLow(c.price, c.allTimeLow)
	}));
}

function byDepthDesc(a: Deal, b: Deal): number {
	return (b.depthPct ?? 0) - (a.depthPct ?? 0) || a.model.localeCompare(b.model);
}

export function belowAverage(deals: Deal[]): Deal[] {
	return deals.filter((d) => d.depthPct !== null && d.depthPct > 0).sort(byDepthDesc);
}

export function atAllTimeLow(deals: Deal[]): Deal[] {
	return deals.filter((d) => d.nearAllTimeLow).sort(byDepthDesc);
}

export function filterDeals(deals: Deal[], filters: DealFilters): Deal[] {
	return deals.filter((d) => {
		if (filters.category && d.category !== filters.category) return false;
		if (filters.retailer && d.retailer !== filters.retailer) return false;
		if (filters.brand && d.brand !== filters.brand) return false;
		return true;
	});
}

const CATEGORY_LABELS = new Map(CATEGORY_OPTIONS.map((o) => [o.value as string, o.label]));

export function categoryFacetCounts(deals: Deal[]): FacetOption[] {
	const counts = new Map<string, number>();
	for (const d of deals) counts.set(d.category, (counts.get(d.category) ?? 0) + 1);
	return [...counts.entries()]
		.map(([value, count]) => ({ value, label: CATEGORY_LABELS.get(value) ?? value, count }))
		.sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

// Adapts a product-level deal to the listing-shaped row OfferRow renders. The
// candidate query only ever returns a listing that is in stock on the latest
// snapshot date, so the stock fields are known-good rather than assumed.
export function dealToOffer(deal: Deal): ListingDisplay {
	return {
		listingId: deal.listingId,
		brand: deal.brand,
		variantName: deal.variantName,
		retailer: deal.retailer,
		listingUrl: deal.listingUrl,
		latestPrice: deal.price,
		latestStock: 'in_stock',
		delisted: false,
		stale: false,
		inStock: true,
		firstSeen: null,
		lastSeen: deal.snapshotDate,
		selected: false
	};
}
