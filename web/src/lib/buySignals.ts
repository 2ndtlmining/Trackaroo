// "Is now a good time to buy?" (#31 core). Pure functions over data the
// product page already loads -- the band's cheapest in-stock price per day,
// retailerLatest and the offer list -- so every figure is explainable from the
// chart right below it and costs no extra query. Facts only, no verdict and no
// composite score (17-Aug "deal score declined" decision).
import { MIN_HISTORY_POINTS } from './constants';
import type { ListingDisplay } from './listingsPanel';
import type { PriceBandPoint } from './models';
import { formatAud } from './formats';
import { daysBetween, upcomingSaleEvent } from './saleEvents';
import { successorFor } from './successors';

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

export type SignalTone = 'good' | 'neutral' | 'warn' | 'bad';
export type SignalIcon = 'check' | 'dash' | 'down' | 'up' | 'calendar' | 'alert';
export interface Signal {
	key: 'percentile' | 'lowest' | 'avg' | 'trend' | 'sale' | 'successor' | 'gathering';
	tone: SignalTone;
	icon: SignalIcon;
	claim: string;
	evidence: string;
}

const MAX_WINDOW_DAYS = 180;
const MINUS = '−'; // same sign as $lib/formats

// Share (0-100) of days in the window whose low was HIGHER than today's price.
// `days` is the calendar span the window covers (first tracked day in the
// window .. asOf), capped at maxDays. Null under the history gate.
export function pricePercentile(
	lows: DailyLow[],
	today: number,
	asOf: string,
	maxDays = MAX_WINDOW_DAYS
): { pct: number; days: number } | null {
	const from = addDays(asOf, -(maxDays - 1));
	const win = lows.filter((p) => p.date >= from && p.date <= asOf);
	if (win.length < MIN_HISTORY_POINTS) return null;
	const higher = win.filter((p) => p.price > today).length;
	return { pct: (higher / win.length) * 100, days: daysBetween(win[0].date, asOf) + 1 };
}

// How long since the price was last strictly lower than today's. When it never
// was, `sinceStart` is true and `days` is how long tracking has run.
export function lowestInDays(
	lows: DailyLow[],
	today: number,
	asOf: string
): { days: number; sinceStart: boolean } | null {
	const upto = lows.filter((p) => p.date <= asOf);
	if (upto.length === 0) return null;
	for (let i = upto.length - 1; i >= 0; i--) {
		if (upto[i].price < today) return { days: daysBetween(upto[i].date, asOf), sinceStart: false };
	}
	return { days: daysBetween(upto[0].date, asOf) + 1, sinceStart: true };
}

// First-to-last change over the daily lows of the 7 days ending asOf; flat
// within +-1%.
export function trend7(
	lows: DailyLow[],
	asOf: string
): { change: number; dir: 'falling' | 'flat' | 'rising' } | null {
	const from = addDays(asOf, -6);
	const win = lows.filter((p) => p.date >= from && p.date <= asOf);
	if (win.length < 2 || win[0].price <= 0) return null;
	const change = ((win[win.length - 1].price - win[0].price) / win[0].price) * 100;
	return { change, dir: change < -1 ? 'falling' : change > 1 ? 'rising' : 'flat' };
}

// '−4%', '+0.5%': one decimal only when it is not a whole number.
function signedPct(value: number): string {
	const r = Math.round(value * 10) / 10;
	return `${r > 0 ? '+' : r < 0 ? MINUS : ''}${Math.abs(r)}%`;
}

function plural(n: number, unit: string): string {
	return `${n} ${unit}${n === 1 ? '' : 's'}`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function shortDate(isoDate: string): string {
	return `${Number(isoDate.slice(8))} ${MONTHS[Number(isoDate.slice(5, 7)) - 1]}`;
}

// Below the history gate only the gathering signal stands in for the
// history-based badges. Sale and successor signals do not depend on history, so
// they are still added (none exist by default, so the gated output is usually
// just [gathering]).
export function buildSignals(input: {
	lows: DailyLow[];
	today: number | null;
	asOf: string | null;
	avg30: number | null;
	series: string | null;
	now: Date;
}): Signal[] {
	const { lows, today, asOf, avg30, series, now } = input;
	const out: Signal[] = [];

	if (lows.length < MIN_HISTORY_POINTS || asOf === null) {
		out.push({
			key: 'gathering',
			tone: 'neutral',
			icon: 'dash',
			claim: `Gathering history (${plural(lows.length, 'day')})`,
			evidence: `Price signals need at least ${MIN_HISTORY_POINTS} days of tracked prices.`
		});
	} else if (today !== null) {
		const pc = pricePercentile(lows, today, asOf);
		if (pc) {
			const good = pc.pct >= 70;
			out.push({
				key: 'percentile',
				tone: good ? 'good' : 'neutral',
				icon: good ? 'check' : 'dash',
				claim: `Cheaper than ${Math.round(pc.pct)}% of days`,
				evidence: `Share of the last ${plural(pc.days, 'day')} with a higher lowest price than today.`
			});
		}
		const lo = lowestInDays(lows, today, asOf);
		if (lo) {
			const good = lo.days >= 30;
			out.push({
				key: 'lowest',
				tone: good ? 'good' : 'neutral',
				icon: good ? 'check' : 'dash',
				claim: lo.sinceStart
					? 'Lowest since tracking began'
					: lo.days === 0
						? 'Above the latest low'
						: `Lowest in ${plural(lo.days, 'day')}`,
				evidence: lo.sinceStart
					? `No lower price in ${plural(lo.days, 'tracked day')}.`
					: `The price was last lower ${plural(lo.days, 'day')} ago.`
			});
		}
		if (avg30 !== null && avg30 > 0) {
			const diff = ((today - avg30) / avg30) * 100;
			const mag = `${Math.round(Math.abs(diff) * 10) / 10}%`;
			const evidence = `Today ${formatAud(today)} against a 30-day average of ${formatAud(avg30)}.`;
			if (diff <= -2) {
				out.push({ key: 'avg', tone: 'good', icon: 'check', claim: `${mag} below its 30-day average`, evidence });
			} else if (diff >= 2) {
				out.push({ key: 'avg', tone: 'bad', icon: 'alert', claim: `${mag} above its 30-day average`, evidence });
			} else {
				out.push({ key: 'avg', tone: 'neutral', icon: 'dash', claim: 'Within 2% of its 30-day average', evidence });
			}
		}
		const tr = trend7(lows, asOf);
		if (tr) {
			out.push({
				key: 'trend',
				tone: tr.dir === 'falling' ? 'good' : tr.dir === 'rising' ? 'warn' : 'neutral',
				icon: tr.dir === 'falling' ? 'down' : tr.dir === 'rising' ? 'up' : 'dash',
				claim: `7-day trend: ${tr.dir} (${signedPct(tr.change)})`,
				evidence: 'Change in the lowest in-stock price over the last 7 days; flat is within 1%.'
			});
		}
	}

	const sale = upcomingSaleEvent(now.toISOString().slice(0, 10));
	if (sale) {
		const { event, startsInDays, running } = sale;
		const when =
			event.start === event.end
				? `Runs ${shortDate(event.start)}.`
				: `Runs ${shortDate(event.start)} to ${shortDate(event.end)}.`;
		out.push({
			key: 'sale',
			tone: 'warn',
			icon: 'calendar',
			claim: running
				? `${event.name} sale on now`
				: `${event.name} starts ${startsInDays === 1 ? 'tomorrow' : `in ${plural(startsInDays, 'day')}`}`,
			evidence: `${when} Retailers often change prices around sale events.`
		});
	}

	const successor = successorFor(series);
	if (successor) {
		out.push({
			key: 'successor',
			tone: 'warn',
			icon: 'alert',
			claim: `Successor announced (${successor})`,
			evidence: 'A newer generation has been announced; stock of this one may clear or dry up.'
		});
	}
	return out;
}
