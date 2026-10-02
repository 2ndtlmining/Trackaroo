import type { DB } from '../db';
import type { Retailer } from '../../types';
import type { RetailerFreshness } from '../../models';

// True when `name` is a table in this DB. The dashboard must keep rendering on a
// DB from before a migration ran (Review Focus 5).
export function tableExists(db: DB, name: string): boolean {
	return (
		db.prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?").get(name) !==
		undefined
	);
}

// Per-retailer currency for the homepage health strip and /healthz.
// The retailer list comes from active_retailers -- the pipeline's
// config.ACTIVE_RETAILERS mirrored into the DB -- so a retailer that has never
// written a row is listed as missing instead of silently absent (R1, 28-Sep:
// Umart on prod). A retailer that is no longer active but has history follows,
// by slug. On a DB without the table, retailers with data are listed by slug.
export function getRetailerFreshness(db: DB): RetailerFreshness[] {
	const latest = db
		.prepare(
			`SELECT l.retailer AS retailer, MAX(s.snapshot_date) AS latest
			 FROM retailer_listings l
			 JOIN price_snapshots s ON s.retailer_listing_id = l.id
			 GROUP BY l.retailer`
		)
		.all() as Array<{ retailer: string; latest: string | null }>;
	const latestBy = new Map(latest.map((r) => [r.retailer, r.latest]));

	const active = tableExists(db, 'active_retailers')
		? (
				db
					.prepare('SELECT retailer FROM active_retailers ORDER BY position, retailer')
					.all() as Array<{ retailer: string }>
			).map((r) => r.retailer)
		: [];
	const inactive = [...latestBy.keys()].filter((r) => !active.includes(r)).sort();

	// One GROUP BY pass, not a correlated MAX(id) subquery re-run per row
	// (final review M4) -- /healthz calls this on every health-strip request.
	const runs = tableExists(db, 'scrape_runs')
		? (db
				.prepare(
					`SELECT r.retailer AS retailer, r.finished_at AS at, r.status AS status, r.matched AS matched
					 FROM scrape_runs r
					 WHERE r.id IN (SELECT MAX(id) FROM scrape_runs GROUP BY retailer)`
				)
				.all() as Array<{ retailer: string; at: string; status: string; matched: number | null }>)
		: [];
	const runBy = new Map(runs.map((r) => [r.retailer, r]));

	return [...active, ...inactive].map((retailer) => {
		const run = runBy.get(retailer);
		return {
			retailer: retailer as Retailer,
			latestSnapshotDate: latestBy.get(retailer) ?? null,
			lastRunAt: run?.at ?? null,
			lastRunStatus: run?.status ?? null,
			lastRunMatched: run?.matched ?? null
		};
	});
}
