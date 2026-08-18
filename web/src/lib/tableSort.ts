export type SortDir = 'asc' | 'desc' | null;

export type SortValue = string | number | null;

// Tri-state column header cycle: unsorted -> ascending -> descending -> unsorted.
export function nextSortDir(current: SortDir): SortDir {
	if (current === null) return 'asc';
	if (current === 'asc') return 'desc';
	return null;
}

// Client-side column sort shared by the dashboard and movers tables. Null
// values always sort last; strings compare locale-aware with numeric ordering.
export function sortRows<T>(
	rows: readonly T[],
	dir: SortDir,
	value: (row: T) => SortValue
): T[] {
	if (!dir) return [...rows];
	const copy = [...rows];
	copy.sort((a, b) => {
		const va = value(a);
		const vb = value(b);
		if (va === null && vb === null) return 0;
		if (va === null) return 1;
		if (vb === null) return -1;
		const cmp =
			typeof va === 'number' && typeof vb === 'number'
				? va - vb
				: String(va).localeCompare(String(vb), undefined, {
						numeric: true,
						sensitivity: 'base'
					});
		return dir === 'asc' ? cmp : -cmp;
	});
	return copy;
}