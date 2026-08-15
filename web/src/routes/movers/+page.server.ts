import { getMovers } from '$lib/server/repos';
import { getDb } from '$lib/server/db';

const WINDOWS = ['24h', '7d', '30d'] as const;
export type WindowKey = (typeof WINDOWS)[number];

const DAYS: Record<WindowKey, number> = { '24h': 1, '7d': 7, '30d': 30 };

export function load({ url }: { url: URL }) {
	const raw = url.searchParams.get('window') ?? '7d';
	const window = (WINDOWS as readonly string[]).includes(raw) ? (raw as WindowKey) : '7d';
	const db = getDb();
	const movers = getMovers(db, DAYS[window]);
	return { movers, window, windows: WINDOWS };
}