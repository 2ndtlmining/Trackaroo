// Pure helpers for the price chart's gap connectors and axis note (#27).

/**
 * Index pairs bridging a run of nulls: the last known point before the run
 * and the next known point after it. Leading and trailing nulls are not gaps.
 */
export function gapSegments(
	dates: string[],
	values: (number | null)[]
): Array<{ from: number; to: number }> {
	const out: Array<{ from: number; to: number }> = [];
	const n = Math.min(dates.length, values.length);
	let last = -1;
	for (let i = 0; i < n; i++) {
		if (values[i] == null) continue;
		if (last >= 0 && i - last > 1) out.push({ from: last, to: i });
		last = i;
	}
	return out;
}

/** True when the y axis includes zero, so no "axis doesn't start at $0" note is needed. */
export function axisStartsAtZero(min: number): boolean {
	return min <= 0;
}
