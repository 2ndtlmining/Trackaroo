// AU sale calendar for the "sale event soon" signal. Rule-based events are
// computed for any year; Click Frenzy and Prime Day have no fixed rule, so they
// are curated per year. CURATED_YEARS must always include next year (a test
// fails when it does not).
export interface SaleEvent {
	name: string;
	start: string; // inclusive ISO date
	end: string; // inclusive ISO date
	// Curated dates not yet announced (R9): the badge and the chart say so.
	estimated?: true;
}

export const CURATED_YEARS = [2026, 2027];

// [name, start, end, estimated]. Set estimated to false once the retailer
// announces the real dates.
const CURATED: Record<number, Array<[string, string, string, boolean]>> = {
	2026: [
		// estimate — replace when announced
		['Prime Day', '2026-07-14', '2026-07-15', true],
		// estimate — replace when announced
		['Click Frenzy', '2026-11-10', '2026-11-11', true]
	],
	2027: [
		// estimate — replace when announced
		['Prime Day', '2027-07-13', '2027-07-14', true],
		// estimate — replace when announced
		['Click Frenzy', '2027-11-09', '2027-11-10', true]
	]
};

function iso(y: number, m: number, d: number): string {
	return new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);
}

function dayNumber(isoDate: string): number {
	const [y, m, d] = isoDate.split('-').map(Number);
	return Date.UTC(y, m - 1, d) / 86_400_000;
}

export function daysBetween(fromIso: string, toIso: string): number {
	return dayNumber(toIso) - dayNumber(fromIso);
}

// Thanksgiving is the 4th Thursday of November; Black Friday is the day after.
function blackFriday(year: number): string {
	const firstDow = new Date(Date.UTC(year, 10, 1)).getUTCDay();
	const firstThursday = 1 + ((4 - firstDow + 7) % 7);
	return iso(year, 11, firstThursday + 21 + 1);
}

export function saleEventsFor(year: number): SaleEvent[] {
	const bf = blackFriday(year);
	const events: SaleEvent[] = [
		{ name: 'EOFY', start: iso(year, 6, 15), end: iso(year, 6, 30) },
		{ name: 'Singles Day', start: iso(year, 11, 11), end: iso(year, 11, 11) },
		// Black Friday through Cyber Monday.
		{ name: 'Black Friday', start: bf, end: iso(year, 11, Number(bf.slice(8)) + 3) },
		{ name: 'Boxing Day', start: iso(year, 12, 26), end: iso(year, 12, 31) }
	];
	for (const [name, start, end, estimated] of CURATED[year] ?? []) {
		events.push(estimated ? { name, start, end, estimated: true } : { name, start, end });
	}
	return events.sort((a, b) => a.start.localeCompare(b.start) || a.name.localeCompare(b.name));
}

export function upcomingSaleEvent(
	todayIso: string,
	horizonDays = 21
): { event: SaleEvent; startsInDays: number; running: boolean } | null {
	const year = Number(todayIso.slice(0, 4));
	// Next year too, so the lookahead works across the year end.
	const events = [...saleEventsFor(year), ...saleEventsFor(year + 1)];
	const running = events.find((e) => e.start <= todayIso && todayIso <= e.end);
	if (running) return { event: running, startsInDays: 0, running: true };
	const next = events.find((e) => e.start > todayIso);
	if (!next) return null;
	const startsInDays = daysBetween(todayIso, next.start);
	return startsInDays <= horizonDays ? { event: next, startsInDays, running: false } : null;
}

// Every event overlapping the inclusive range [fromIso, toIso], in date order:
// the price chart marks these on its x axis. An event that began before the
// range and is still running at its start counts.
export function saleEventsInRange(fromIso: string, toIso: string): SaleEvent[] {
	if (fromIso > toIso) return [];
	const out: SaleEvent[] = [];
	for (let y = Number(fromIso.slice(0, 4)); y <= Number(toIso.slice(0, 4)); y++) {
		for (const e of saleEventsFor(y)) if (e.start <= toIso && e.end >= fromIso) out.push(e);
	}
	return out;
}
