import {
	getCategoryCounts,
	getCheapestPerModel,
	getDealCandidates,
	getHeaderStats,
	getMovers,
	getRetailerFreshness,
	type Mover
} from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { belowAverage, toDeals, type Deal } from '$lib/deals';
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

export function load() {
	const db = getDb();
	const stats = getHeaderStats(db);
	const counts = getCategoryCounts(db);
	// Same source as /deals, so the two surfaces can never disagree about
	// what counts as a deal or how deep it is.
	const allDeals = belowAverage(toDeals(getDealCandidates(db)));
	const movers = getMovers(db, HOME_MOVER_DAYS);

	const sections = SECTIONS.map(({ category, title }) => {
		const cheapest = getCheapestPerModel(db, category);
		const inCategory = (m: Mover) => m.category === category && m.pctChange !== null;
		const drops = movers
			.filter((m) => inCategory(m) && (m.pctChange as number) < 0)
			.sort((a, b) => (a.pctChange as number) - (b.pctChange as number));
		const rises = movers
			.filter((m) => inCategory(m) && (m.pctChange as number) > 0)
			.sort((a, b) => (b.pctChange as number) - (a.pctChange as number));

		return {
			category,
			title,
			href: `/products?category=${category}`,
			trackedCount: counts.get(category) ?? 0,
			cheapestPrice: cheapest.reduce<number | null>(
				(min, c) => (min === null || c.price < min ? c.price : min),
				null
			),
			deals: allDeals.filter((d: Deal) => d.category === category).slice(0, PER_COLUMN),
			drops: drops.slice(0, PER_COLUMN),
			rises: rises.slice(0, PER_COLUMN)
		};
	});

	return {
		retailers: retailerHealth(getRetailerFreshness(db)),
		latestSnapshotDate: stats.latestSnapshotDate,
		snapshotDays: stats.snapshotDays,
		snapshotCount: stats.snapshotCount,
		sections
	};
}
