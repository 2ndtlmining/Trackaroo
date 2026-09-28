import { getMovers, getSparklines } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { memo } from '$lib/server/cache';

const WINDOWS = ['24h', '7d', '30d'] as const;
export type WindowKey = (typeof WINDOWS)[number];

const DAYS: Record<WindowKey, number> = { '24h': 1, '7d': 7, '30d': 30 };

export function load({
	url,
	setHeaders
}: {
	url: URL;
	setHeaders: (headers: Record<string, string>) => void;
}) {
	const raw = url.searchParams.get('window') ?? '7d';
	const window = (WINDOWS as readonly string[]).includes(raw) ? (raw as WindowKey) : '7d';
	// 85% of listings don't move in a week; shipping them made /movers 1.5 MB
	// (#5). They stay one click away behind ?all=1.
	const showAll = url.searchParams.get('all') === '1';
	const db = getDb();
	setHeaders({ 'cache-control': 'public, max-age=60, stale-while-revalidate=300' });
	const days = DAYS[window];
	const all = memo(db, `movers:${days}`, () => getMovers(db, days));
	const movers = showAll
		? all
		: all.filter((m) => !m.notEnoughHistory && m.change !== null && Math.abs(m.change) >= 0.005);
	// showAll changes which listing ids need sparklines, so it must be in the
	// key -- otherwise the second variant to load in a data_version would
	// serve the first variant's (wrong) set of sparklines.
	const sparklines = memo(db, `sparklines:${days}:${showAll}`, () =>
		getSparklines(db, movers.map((m) => m.listingId), days)
	);
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