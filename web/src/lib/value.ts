// Pure price-to-performance maths (#33). No I/O, no DB.
import type { ValueCoverage } from './models';

export interface ValuePoint {
	id: number;
	name: string;
	price: number;
	perf: number;
	vramGb: number | null;
}

const ok = (n: number | null): n is number => n != null && Number.isFinite(n) && n > 0;

/** Performance per A$1,000: perf / price * 1000. Null for a missing or non-positive input. */
export function perfPerKilo(price: number | null, perf: number | null): number | null {
	return ok(price) && ok(perf) ? (perf / price) * 1000 : null;
}

/** A$ per performance point: price / perf. Null for a missing or non-positive input. */
export function audPerPoint(price: number | null, perf: number | null): number | null {
	return ok(price) && ok(perf) ? price / perf : null;
}

/**
 * Ids on the price/performance frontier, price ascending. A point is dropped
 * only when another has price <= and perf >= with at least one strict, so
 * ties and identical points all stay.
 */
export function paretoFrontier(points: ValuePoint[]): number[] {
	return points
		.filter(
			(p) =>
				!points.some(
					(q) =>
						q !== p && q.price <= p.price && q.perf >= p.perf && (q.price < p.price || q.perf > p.perf)
				)
		)
		.sort((a, b) => a.price - b.price || b.perf - a.perf)
		.map((p) => p.id);
}

export const BUDGETS: readonly number[] = [400, 700, 1000, 1500, 2500];

export interface BudgetPick {
	max: number;
	winner: ValuePoint | null;
	runnerUp: ValuePoint | null;
	gap: number | null;
}

/** Best performance at or under each budget; a perf tie goes to the lower price. */
export function bestPerBudget(points: ValuePoint[], opts: { exclude8gb?: boolean } = {}): BudgetPick[] {
	const pool = opts.exclude8gb ? points.filter((p) => p.vramGb == null || p.vramGb > 8) : points;
	return BUDGETS.map((max) => {
		const ranked = pool.filter((p) => p.price <= max).sort((a, b) => b.perf - a.perf || a.price - b.price);
		const winner = ranked[0] ?? null;
		const runnerUp = ranked[1] ?? null;
		const gap = winner && runnerUp && runnerUp.perf > 0 ? (winner.perf - runnerUp.perf) / runnerUp.perf : null;
		return { max, winner, runnerUp, gap };
	});
}

/** Performance coverage restricted to the required tiers (current and current-1). */
export function tierCoverage(rows: { tier: string | null; perf: number | null }[]): { withPerf: number; tracked: number } {
	const req = rows.filter((r) => r.tier === 'current' || r.tier === 'current-1');
	return { tracked: req.length, withPerf: req.filter((r) => r.perf != null).length };
}

/** Counts behind "N of M tracked have performance data" (R6). */
export function valueCoverage(rows: { price: number | null; perf: number | null }[]): ValueCoverage {
	const withPerf = rows.filter((r) => r.perf != null).length;
	const withPerfAndPrice = rows.filter((r) => r.perf != null && ok(r.price)).length;
	return {
		tracked: rows.length,
		withPerf,
		withoutPerf: rows.length - withPerf,
		withPerfAndPrice,
		noPrice: withPerf - withPerfAndPrice
	};
}
