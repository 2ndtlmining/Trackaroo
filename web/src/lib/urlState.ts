// URL state for client-filtered pages (#26). Pure, so garbage in a shared or
// hand-edited URL is pinned by tests: it degrades to defaults, never a 500.
export const MAX_COMPARE = 4;

export function parseCompareIds(raw: string | null): number[] {
	if (!raw) return [];
	const ids: number[] = [];
	for (const part of raw.split(',')) {
		const n = Number(part.trim());
		if (Number.isInteger(n) && n > 0 && !ids.includes(n)) ids.push(n);
		if (ids.length === MAX_COMPARE) break;
	}
	return ids;
}

// `search` with each key set, replaced, or removed (null or ''), every other
// parameter kept in place. Returns '' or '?…', ready to append to a path.
export function withParams(
	search: string | URLSearchParams,
	changes: Record<string, string | null>
): string {
	const params = new URLSearchParams(search);
	for (const [key, value] of Object.entries(changes)) {
		if (value === null || value === '') params.delete(key);
		else params.set(key, value);
	}
	const qs = params.toString();
	return qs ? `?${qs}` : '';
}
