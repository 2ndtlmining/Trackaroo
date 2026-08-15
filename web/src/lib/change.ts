import type { ChangeDirection } from './types';

export interface ChangeInput {
	latestPrice: number;
	windowStartPrice: number | null;
	pointsInWindow: number;
	lastSnapshotAt: string | null;
	now?: Date | string;
	staleThresholdDays?: number;
}

export const STALE_THRESHOLD_DAYS = 3;
const FLAT_EPSILON = 0.005;

function toTime(value: Date | string): number {
	return typeof value === 'string' ? new Date(value).getTime() : value.getTime();
}

export function classifyChange(input: ChangeInput): ChangeDirection {
	const {
		latestPrice,
		windowStartPrice,
		pointsInWindow,
		lastSnapshotAt,
		now = new Date(),
		staleThresholdDays = STALE_THRESHOLD_DAYS
	} = input;

	if (windowStartPrice === null || pointsInWindow < 2) return 'insufficient';

	if (lastSnapshotAt !== null) {
		const ageDays = (toTime(now) - toTime(lastSnapshotAt)) / 86_400_000;
		if (ageDays > staleThresholdDays) return 'stale';
	}

	const delta = latestPrice - windowStartPrice;
	if (Math.abs(delta) < FLAT_EPSILON) return 'flat';
	return delta > 0 ? 'up' : 'down';
}