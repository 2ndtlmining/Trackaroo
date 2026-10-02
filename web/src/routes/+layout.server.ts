import { getHeaderStats, getProductIndex } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { getDiscoverPendingCount } from '$lib/server/discover';
import { memo } from '$lib/server/cache';
import { buildVersion, releaseVersion } from '$lib/server/version';

// Runs on every page, so this is the highest-traffic day-level query on the
// site (#28): the pipeline writes once a day, but without memo() this scanned
// price_snapshots on every request.
export function load() {
	const db = getDb();
	return {
		stats: memo(db, 'headerStats', () => getHeaderStats(db)),
		productIndex: memo(db, 'productIndex', () => getProductIndex(db)),
		// A constant for the process: not memoised (#3).
		version: buildVersion(),
		release: releaseVersion(),
		// Not memoised: it changes the moment a Track/Ignore is clicked.
		discoverPending: getDiscoverPendingCount(db)
	};
}