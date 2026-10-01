import {
	getAvailableCounts,
	getCategoryCounts,
	getDealCandidates,
	getProductMoves,
	getRetailerFreshness,
	type HeaderStats
} from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { memo } from '$lib/server/cache';
import { belowAverage, toDeals, type Deal } from '$lib/deals';
import { topProductMoves } from '$lib/movers';
import { retailerHealth } from '$lib/health';
import type { Category } from '$lib/types';

// Fixed 7 days, not the /movers window selector: the scrape cadence is daily,
// so a 24-hour window is a single snapshot pair and one missed run would empty
// the section outright (spec §5).
const HOME_MOVER_DAYS = 7;
const PER_COLUMN = 3;

const SECTIONS: Array<{ category: Category; title: string }> = [
	{ category: 'gpu', title: 'GPUs' },
	{ category: 'cpu', title: 'CPUs' }
];

export async function load({
	parent,
	setHeaders
}: {
	parent: () => Promise<{ stats: HeaderStats }>;
	setHeaders: (headers: Record<string, string>) => void;
}) {
	const db = getDb();
	setHeaders({ 'cache-control': 'public, max-age=60, stale-while-revalidate=300' });
	// The layout already computed this (it's on every page); no need to query
	// it again here.
	const { stats } = await parent();
	const counts = memo(db, 'categoryCounts', () => getCategoryCounts(db));
	const available = memo(db, 'availableCounts', () => getAvailableCounts(db));
	const allCandidates = memo(db, 'dealCandidates', () => getDealCandidates(db));
	// Same source as /deals, so the two surfaces can never disagree about
	// what counts as a deal or how deep it is.
	const allDeals = belowAverage(toDeals(allCandidates));
	const moves = memo(db, 'productMoves:7', () => getProductMoves(db, HOME_MOVER_DAYS));

	const sections = SECTIONS.map(({ category, title }) => {
		// Product-level: the cheapest in-stock price, not one SKU's (D7).
		const drops = topProductMoves(moves, category, 'down', PER_COLUMN);
		const rises = topProductMoves(moves, category, 'up', PER_COLUMN);

		return {
			category,
			title,
			href: `/products?category=${category}`,
			trackedCount: counts.get(category) ?? 0,
			availableCount: available.get(category) ?? 0,
			cheapestPrice: allCandidates
				.filter((c) => c.category === category)
				.reduce<number | null>((min, c) => (min === null || c.price < min ? c.price : min), null),
			deals: allDeals.filter((d: Deal) => d.category === category).slice(0, PER_COLUMN),
			drops,
			rises
		};
	});

	return {
		retailers: retailerHealth(memo(db, 'retailerFreshness', () => getRetailerFreshness(db))),
		latestSnapshotDate: stats.latestSnapshotDate,
		snapshotDays: stats.snapshotDays,
		snapshotCount: stats.snapshotCount,
		dbSizeBytes: stats.dbSizeBytes,
		sections
	};
}
