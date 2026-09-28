// Day-level query memo. The pipeline writes once a day, yet every request
// re-ran the same scans of price_snapshots (header stats 4x, deal candidates,
// movers). SQLite's data_version changes whenever ANOTHER connection commits,
// so the cache drops itself the moment the pipeline or an alert write lands --
// no TTL to tune, no stale page after a scrape.
//
// Values are shared between requests: callers must not mutate them.
import type { DB } from './db';

let version: number | null = null;
const store = new Map<string, unknown>();

export function memo<T>(db: DB, key: string, compute: () => T): T {
	const v = db.pragma('data_version', { simple: true }) as number;
	if (v !== version) {
		store.clear();
		version = v;
	}
	if (!store.has(key)) store.set(key, compute());
	return store.get(key) as T;
}

// Tests only.
export function _resetMemo(): void {
	version = null;
	store.clear();
}
