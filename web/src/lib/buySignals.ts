// "Is now a good time to buy?" (#31 core). Pure functions over data the
// product page already loads -- the band's cheapest in-stock price per day,
// retailerLatest and the offer list -- so every figure is explainable from the
// chart right below it and costs no extra query. Facts only, no verdict and no
// composite score (17-Aug "deal score declined" decision).
import { MIN_HISTORY_POINTS } from './constants';
import type { ListingDisplay } from './listingsPanel';
import type { PriceBandPoint } from './server/repos';

export interface DailyLow {
	date: string;
	price: number;
}

export function dailyLows(band: PriceBandPoint[]): DailyLow[] {
	return band.filter((p) => p.low !== null).map((p) => ({ date: p.date, price: p.low as number }));
}

// 'YYYY-MM-DD' arithmetic in UTC, so the answer never depends on the server's
// or the browser's timezone.
export function addDays(iso: string, days: number): string {
	const [y, m, d] = iso.split('-').map(Number);
	return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

export interface LowSummary {
	low: number;
	// The most recent day the price was at `low`: "how long ago was it this cheap?"
	lowDate: string;
	// First tracked day. "Lowest since <since>" -- never "all-time" (D5).
	since: string;
	today: number | null;
	// Percent today sits above the low; null when nothing is in stock today.
	pctAbove: number | null;
	atLow: boolean;
}

export function lowSummary(lows: DailyLow[], today: number | null): LowSummary | null {
	if (lows.length === 0) return null;
	let low = lows[0].price;
	let lowDate = lows[0].date;
	for (const p of lows) {
		if (p.price <= low) {
			low = p.price;
			lowDate = p.date;
		}
	}
	const atLow = today !== null && today <= low;
	const pctAbove = today === null || low === 0 ? null : Math.max(0, ((today - low) / low) * 100);
	return { low, lowDate, since: lows[0].date, today, pctAbove, atLow };
}

export interface WindowStats {
	days: number;
	points: number;
	low: number | null;
	median: number | null;
	high: number | null;
	// At least MIN_HISTORY_POINTS days: the same gate as every average on the site.
	enough: boolean;
}

// Inclusive N-day window ending on `asOf`: 30 days is asOf-29 .. asOf, the same
// arithmetic as getProductStats (#6/D4).
export function windowStats(lows: DailyLow[], asOf: string, days: number): WindowStats {
	const from = addDays(asOf, -(days - 1));
	const prices = lows
		.filter((p) => p.date >= from && p.date <= asOf)
		.map((p) => p.price)
		.sort((a, b) => a - b);
	const n = prices.length;
	const median =
		n === 0
			? null
			: n % 2 === 1
				? prices[(n - 1) / 2]
				: Math.round(((prices[n / 2 - 1] + prices[n / 2]) / 2) * 100) / 100;
	return {
		days,
		points: n,
		low: n ? prices[0] : null,
		median,
		high: n ? prices[n - 1] : null,
		enough: n >= MIN_HISTORY_POINTS
	};
}

// The window anchor: the newest snapshot any retailer has, so a product that
// sold out in July does not show July prices labelled "last 30 days".
export function asOfDate(retailerLatest: Record<string, string>, lows: DailyLow[]): string | null {
	const dates = [...Object.values(retailerLatest)];
	if (lows.length > 0) dates.push(lows[lows.length - 1].date);
	return dates.length ? dates.sort()[dates.length - 1] : null;
}

export interface RetailerOffer {
	retailer: string;
	// Cheapest buyable listing (in stock, not delisted, not stale).
	cheapest: number | null;
	cheapestUrl: string | null;
	inStock: number;
	// Listings the retailer still carries (not delisted or stale), in stock or not.
	listings: number;
}

export function whereToBuy(offers: ListingDisplay[]): RetailerOffer[] {
	const byRetailer = new Map<string, RetailerOffer>();
	for (const o of offers) {
		if (o.delisted || o.stale) continue;
		let r = byRetailer.get(o.retailer);
		if (!r) {
			r = { retailer: o.retailer, cheapest: null, cheapestUrl: null, inStock: 0, listings: 0 };
			byRetailer.set(o.retailer, r);
		}
		r.listings += 1;
		if (!o.inStock || o.latestPrice === null) continue;
		r.inStock += 1;
		if (r.cheapest === null || o.latestPrice < r.cheapest) {
			r.cheapest = o.latestPrice;
			r.cheapestUrl = o.listingUrl;
		}
	}
	return [...byRetailer.values()].sort((a, b) => {
		if (a.cheapest === null && b.cheapest === null) return a.retailer.localeCompare(b.retailer);
		if (a.cheapest === null) return 1;
		if (b.cheapest === null) return -1;
		return a.cheapest - b.cheapest || a.retailer.localeCompare(b.retailer);
	});
}
