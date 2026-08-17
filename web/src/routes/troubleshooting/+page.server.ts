import { getCoverageSummary } from '$lib/server/repos';
import { getDb } from '$lib/server/db';

export function load() {
	const db = getDb();
	return { summary: getCoverageSummary(db) };
}