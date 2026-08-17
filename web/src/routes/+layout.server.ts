import { getHeaderStats, getProductIndex } from '$lib/server/repos';
import { getDb } from '$lib/server/db';

export function load() {
	const db = getDb();
	return {
		stats: getHeaderStats(db),
		productIndex: getProductIndex(db)
	};
}