// The signature segmented range bar (#22): 6 equal segments, today's
// position filled. Segments 0-1 read as cheap (--down), 2-3 as middling
// (--accent), 4-5 as dear (--up).
export const RANGE_SEGMENTS = 6;

/** Which segment (0..5) a position in [0,1] falls in; null when there is no position. */
export function filledSegment(position: number | null): number | null {
	if (position === null || !Number.isFinite(position)) return null;
	const clamped = Math.min(1, Math.max(0, position));
	return Math.min(RANGE_SEGMENTS - 1, Math.floor(clamped * RANGE_SEGMENTS));
}

export const SEGMENT_TONE = ['bg-down', 'bg-down', 'bg-accent', 'bg-accent', 'bg-up', 'bg-up'] as const;

/** Position of `current` within [low, high], clamped to [0,1]; null for a flat range. */
export function rangePosition(current: number, low: number, high: number): number | null {
	if (!(high > low)) return null;
	return Math.min(1, Math.max(0, (current - low) / (high - low)));
}
