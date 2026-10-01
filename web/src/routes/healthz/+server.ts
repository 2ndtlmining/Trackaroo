// Liveness + what-is-running probe (#9), used by the Docker HEALTHCHECK, CI's
// boot smoke test and Phase 6's redeploy script.
//
// ok means "this process can open and query the DB". Freshness is reported but
// never turns the check unhealthy: staleness is the heartbeat's and the
// staleness monitor's job, and a stale-but-running container must not be
// restarted by an autoheal watcher.
import { json } from '@sveltejs/kit';
import { getDb } from '$lib/server/db';
import { getRetailerFreshness } from '$lib/server/repos';
import { buildVersion } from '$lib/server/version';

const NO_STORE = { 'cache-control': 'no-store' };

export function GET(): Response {
	const version = buildVersion();
	try {
		const retailers = getRetailerFreshness(getDb()).map((r) => ({
			retailer: r.retailer,
			latestSnapshotDate: r.latestSnapshotDate,
			lastRunAt: r.lastRunAt ?? null,
			lastRunStatus: r.lastRunStatus ?? null
		}));
		return json({ ok: true, version, retailers }, { headers: NO_STORE });
	} catch (e) {
		return json(
			{ ok: false, version, error: e instanceof Error ? e.message : String(e) },
			{ status: 503, headers: NO_STORE }
		);
	}
}
