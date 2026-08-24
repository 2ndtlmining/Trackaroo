// Headline stats for the product page: the cheapest buyable price and the two
// deltas that answer "is now a good time to buy". Separate from offers.ts,
// which decides which rows to show.
import { MIN_HISTORY_POINTS } from './constants';
import { deltaVsAvg30, type ListingDisplay } from './offers';
import type { PriceBandPoint, ProductStats } from './server/repos';

export interface Headline {
	currentPrice: number | null;
	currentRetailer: string | null;
	allTimeLow: number | null;
	allTimeHigh: number | null;
	// Null when there is not enough history to trust it.
	avg30: number | null;
	vsAvg30Pct: number | null;
	vsAllTimeLowPct: number | null;
	// 0..1 for the range bar, or null when a bar would be meaningless.
	rangePosition: number | null;
}

export function buildHeadline(
	offers: ListingDisplay[],
	band: PriceBandPoint[],
	stats: ProductStats
): Headline {
	let currentPrice: number | null = null;
	let currentRetailer: string | null = null;
	for (const o of offers) {
		if (!o.inStock || o.delisted || o.latestPrice === null) continue;
		if (currentPrice === null || o.latestPrice < currentPrice) {
			currentPrice = o.latestPrice;
			currentRetailer = o.retailer;
		}
	}

	let allTimeLow: number | null = null;
	let allTimeHigh: number | null = null;
	for (const p of band) {
		if (p.low !== null && (allTimeLow === null || p.low < allTimeLow)) allTimeLow = p.low;
		if (p.high !== null && (allTimeHigh === null || p.high > allTimeHigh)) allTimeHigh = p.high;
	}

	// The same guard the old "30d avg" chip used: a three-day average is not an
	// average, and presenting one as a deal signal would mislead.
	const avg30 =
		stats.avg30 !== null && stats.avg30Points >= MIN_HISTORY_POINTS ? stats.avg30 : null;

	const vsAvg30Pct = deltaVsAvg30(currentPrice, avg30);

	const vsAllTimeLowPct =
		currentPrice !== null && allTimeLow !== null && allTimeLow !== 0
			? ((currentPrice - allTimeLow) / allTimeLow) * 100
			: null;

	const rangePosition =
		currentPrice !== null && allTimeLow !== null && allTimeHigh !== null && allTimeHigh > allTimeLow
			? Math.min(1, Math.max(0, (currentPrice - allTimeLow) / (allTimeHigh - allTimeLow)))
			: null;

	return {
		currentPrice,
		currentRetailer,
		allTimeLow,
		allTimeHigh,
		avg30,
		vsAvg30Pct,
		vsAllTimeLowPct,
		rangePosition
	};
}
