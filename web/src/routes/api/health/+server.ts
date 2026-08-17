import { json } from '@sveltejs/kit';
import { getDb } from '$lib/server/db';
import { getCoverageSummary } from '$lib/server/repos';

// Temporary diagnostic JSON endpoint (backs the /troubleshooting page).
// Returns the same coverage summary the page renders, so external tooling
// (cron, the user) can check retailer/model freshness without a browser.
export function GET() {
	const db = getDb();
	return json(getCoverageSummary(db));
}