// Series -> successor label ("RTX 60"), maintained by hand when a next
// generation is announced. Starts empty: the badge only appears once the owner
// has filled in a real announcement.
export const SUCCESSORS: Record<string, string> = {};

export function successorFor(series: string | null): string | null {
	if (!series || !Object.prototype.hasOwnProperty.call(SUCCESSORS, series)) return null;
	return SUCCESSORS[series] || null;
}
