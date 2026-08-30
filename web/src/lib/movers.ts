// Dashboard-side shaping of the per-listing mover rows returned by getMovers.
//
// getMovers is deliberately per-LISTING: /movers wants every SKU, and it has a
// Variant column to tell them apart. The dashboard's three-row summary has no
// such column, so three listings of one card (PCCG carries the RTX 5070 as
// Ventus 3X / Shadow 2X / Shadow 3X) rendered as the same "GeForce RTX 5070 /
// pccg" row three times with three different percentages. Collapsing to one
// row per product is what makes those three slots show three different cards.
import type { Mover } from './server/repos';
import type { Category } from './types';

export type MoverDirection = 'up' | 'down';

/**
 * Pick the biggest movers in one direction, at most one row per product.
 *
 * Listings without a percentage, without enough history, or exactly flat are
 * excluded: /movers badges thin listings as "Not enough history", and the
 * dashboard row has no equivalent badge, so an unqualified listing would read
 * as authoritative here.
 *
 * Where a product has several qualifying listings the steepest move in the
 * requested direction represents it, ties broken by listing id so the order is
 * stable between renders.
 */
export function topMoversByProduct(
	movers: Mover[],
	category: Category,
	direction: MoverDirection,
	limit: number
): Mover[] {
	const qualifies = (m: Mover): boolean => {
		if (m.category !== category) return false;
		if (m.pctChange === null) return false;
		if (m.notEnoughHistory) return false;
		return direction === 'up' ? m.pctChange > 0 : m.pctChange < 0;
	};

	// Steepest move wins; equal moves fall back to listing id so a redeploy
	// doesn't silently reshuffle the dashboard.
	const beats = (candidate: Mover, incumbent: Mover): boolean => {
		const a = candidate.pctChange as number;
		const b = incumbent.pctChange as number;
		if (a !== b) return direction === 'up' ? a > b : a < b;
		return candidate.listingId < incumbent.listingId;
	};

	const best = new Map<number, Mover>();
	for (const m of movers) {
		if (!qualifies(m)) continue;
		const incumbent = best.get(m.productId);
		if (!incumbent || beats(m, incumbent)) best.set(m.productId, m);
	}

	return [...best.values()]
		.sort((a, b) => {
			const av = a.pctChange as number;
			const bv = b.pctChange as number;
			if (av !== bv) return direction === 'up' ? bv - av : av - bv;
			return a.listingId - b.listingId;
		})
		.slice(0, limit);
}
