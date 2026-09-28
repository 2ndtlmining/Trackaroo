import { getMovers, getSparklines } from '$lib/server/repos';
import { getDb } from '$lib/server/db';

const WINDOWS = ['24h', '7d', '30d'] as const;
export type WindowKey = (typeof WINDOWS)[number];

const DAYS: Record<WindowKey, number> = { '24h': 1, '7d': 7, '30d': 30 };

export function load({ url }: { url: URL }) {
	const raw = url.searchParams.get('window') ?? '7d';
	const window = (WINDOWS as readonly string[]).includes(raw) ? (raw as WindowKey) : '7d';
	// 85% of listings don't move in a week; shipping them made /movers 1.5 MB
	// (#5). They stay one click away behind ?all=1.
	const showAll = url.searchParams.get('all') === '1';
	const db = getDb();
	const all = getMovers(db, DAYS[window]);
	const movers = showAll
		? all
		: all.filter((m) => !m.notEnoughHistory && m.change !== null && Math.abs(m.change) >= 0.005);
	const sparklines = getSparklines(db, movers.map((m) => m.listingId), DAYS[window]);
	return {
		movers: movers.map((m) => ({
			...m,
			sparkline: (sparklines.get(m.listingId) ?? []).map((p) => ({ date: p.date, price: p.price }))
		})),
		window,
		windows: WINDOWS,
		showAll,
		hiddenCount: all.length - movers.length
	};
}