import { getHeaderStats } from '$lib/server/repos';
import { getDb } from '$lib/server/db';

export function load() {
	return {
		stats: getHeaderStats(getDb())
	};
}