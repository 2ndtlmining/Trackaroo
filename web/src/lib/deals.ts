// Deal ranking for /deals. Pure — no DB access — so every rule here is
// unit-testable. Answers two different questions that must not be blended:
// "is this cheap versus its own recent history" (below the 30-day average)
// and "is this cheap versus all history" (at or near the all-time low).
//
// A deal must clear BOTH floors -- at least DEAL_MIN_PCT and DEAL_MIN_AUD
// below its own 30-day average -- so a $0.13 (-0.1%) wobble or a 3% move on a
// $9 part never gets labelled a deal (#6, 28-Sep finding). An all-time low
// only counts as "earned" if the price was at least EARNED_LOW_RISE_PCT
// higher at some point in the window -- a flat line isn't a drop. shownDeals
// is the union both sections actually render, so the page's row count and its
// facet counts always agree.
import { DEAL_MIN_AUD, DEAL_MIN_PCT, EARNED_LOW_RISE_PCT, MIN_HISTORY_POINTS } from './constants';
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
	// Dollars below the 30-day average. Positive = cheaper.
	savingAud: number | null;
	nearAllTimeLow: boolean;
	// Near the low AND the price was EARNED_LOW_RISE_PCT higher inside the
	// window: a drop, not a flat line (#6).
	earnedLow: boolean;
	// True only when the price actually IS the (new) all-time low, not just
	// within the near-low tolerance band -- distinguishes "Lowest since" from
	// "Near low since" (M3, 28-Sep finding).
	atNewLow: boolean;
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

// Zero-tolerance version of isNearAllTimeLow: true only when the price
// actually reached (or beat) the recorded all-time low, not merely within
// NEAR_ALL_TIME_LOW_PCT of it. The "Lowest since" badge claims the former;
// isNearAllTimeLow/earnedLow only guarantee the latter, which overclaimed
// (M3, 28-Sep finding).
export function isAtNewLow(price: number, allTimeLow: number | null): boolean {
	if (allTimeLow === null) return false;
	return price <= allTimeLow;
}

export function isEarnedLow(c: DealCandidate): boolean {
	return (
		isNearAllTimeLow(c.price, c.allTimeLow) &&
		c.windowHigh !== null &&
		c.windowHigh >= c.price * (1 + EARNED_LOW_RISE_PCT / 100)
	);
}

export function toDeals(candidates: DealCandidate[]): Deal[] {
	return candidates.filter(isEligible).map((c) => ({
		...c,
		depthPct: dealDepthPct(c.price, c.avg30),
		savingAud: c.avg30 === null ? null : Math.round((c.avg30 - c.price) * 100) / 100,
		nearAllTimeLow: isNearAllTimeLow(c.price, c.allTimeLow),
		earnedLow: isEarnedLow(c),
		atNewLow: isAtNewLow(c.price, c.allTimeLow)
	}));
}

function byDepthDesc(a: Deal, b: Deal): number {
	return (b.depthPct ?? 0) - (a.depthPct ?? 0) || a.model.localeCompare(b.model);
}

function isRealDeal(d: Deal): boolean {
	return (
		d.depthPct !== null &&
		d.depthPct >= DEAL_MIN_PCT &&
		d.savingAud !== null &&
		d.savingAud >= DEAL_MIN_AUD
	);
}

export function belowAverage(deals: Deal[]): Deal[] {
	return deals.filter(isRealDeal).sort(byDepthDesc);
}

// Earned lows that are NOT already listed above: one row per product (#6).
export function atAllTimeLow(deals: Deal[]): Deal[] {
	return deals.filter((d) => d.earnedLow && !isRealDeal(d)).sort(byDepthDesc);
}

// The union of both sections -- what the page actually renders, so the
// facets it counts never overstate what's shown (#6, 28-Sep finding).
export function shownDeals(deals: Deal[]): Deal[] {
	return deals.filter((d) => isRealDeal(d) || d.earnedLow);
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
