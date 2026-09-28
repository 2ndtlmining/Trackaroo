import {
	getAvailableCounts,
	getCategoryCounts,
	getDealCandidates,
	getMovers,
	getRetailerFreshness,
	type HeaderStats
} from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { belowAverage, toDeals, type Deal } from '$lib/deals';
import { topMoversByProduct } from '$lib/movers';
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

export async function load({ parent }: { parent: () => Promise<{ stats: HeaderStats }> }) {
	const db = getDb();
	// The layout already computed this (it's on every page); no need to query
	// it again here.
	const { stats } = await parent();
	const counts = getCategoryCounts(db);
	const available = getAvailableCounts(db);
	const allCandidates = getDealCandidates(db);
	// Same source as /deals, so the two surfaces can never disagree about
	// what counts as a deal or how deep it is.
	const allDeals = belowAverage(toDeals(allCandidates));
	const movers = getMovers(db, HOME_MOVER_DAYS);

	const sections = SECTIONS.map(({ category, title }) => {
		// One row per product: getMovers is per-listing, and a retailer carrying
		// several SKUs of one card (PCCG has three MSI RTX 5070s) would otherwise
		// fill all three slots with what looks like the same row repeated.
		const drops = topMoversByProduct(movers, category, 'down', PER_COLUMN);
		const rises = topMoversByProduct(movers, category, 'up', PER_COLUMN);

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
		retailers: retailerHealth(getRetailerFreshness(db)),
		latestSnapshotDate: stats.latestSnapshotDate,
		snapshotDays: stats.snapshotDays,
		snapshotCount: stats.snapshotCount,
		dbSizeBytes: stats.dbSizeBytes,
		sections
	};
}
