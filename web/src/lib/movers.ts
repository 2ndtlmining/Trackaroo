// Shaping of mover rows. /movers ranks, groups and sorts the per-LISTING rows
// from getMovers (it has a Variant column to tell SKUs apart). The homepage's
// three-row summary is product-level instead: see topProductMoves (D7).
import type { Mover, ProductMove } from './server/repos';
import type { Category } from './types';

export type MoverDirection = 'up' | 'down';

// What a homepage mover row needs; satisfied by both a per-listing Mover and a
// product-level ProductMove.
export type MoverRowData = Pick<
	Mover,
	'productId' | 'model' | 'newPrice' | 'pctChange' | 'retailer' | 'variantName'
>;

// The homepage's biggest product-level moves in one direction (D7). Exactly
// flat products are excluded; ties fall back to product id so the order is
// stable between renders. filter() copies before sort(): `moves` is
// memo-shared (Review Focus 5).
export function topProductMoves(
	moves: readonly ProductMove[],
	category: Category,
	direction: MoverDirection,
	limit: number
): ProductMove[] {
	return moves
		.filter(
			(m) => m.category === category && (direction === 'up' ? m.pctChange > 0 : m.pctChange < 0)
		)
		.sort(
			(a, b) =>
				(direction === 'up' ? b.pctChange - a.pctChange : a.pctChange - b.pctChange) ||
				a.productId - b.productId
		)
		.slice(0, limit);
}

export type MoverSortKey = 'abs' | 'pct' | 'price';

// A row with no trustworthy change value: either too little history to trust
// it (badged "Not enough history") or literally no prior price to compare
// against. Shared by every sort on this page so an unknown row can never
// out-rank a real, priced move under any sort key or direction (#5 follow-up:
// the column-header sort used to pass a notEnoughHistory row's raw non-null
// `change` straight through, so a 2-point row could still land among real
// movers when sorted by the Change column).
export function isUnknownMover(m: Mover): boolean {
	return m.notEnoughHistory || m.change === null;
}

// Rows without a change ("Not enough history", null change) always sort last:
// sorting by |change| treated null as -Infinity, whose magnitude is Infinity,
// so brand-new listings led the page (#5).
export function sortMovers(rows: readonly Mover[], key: MoverSortKey): Mover[] {
	return [...rows].sort((a, b) => {
		const ua = isUnknownMover(a);
		const ub = isUnknownMover(b);
		if (ua !== ub) return ua ? 1 : -1;
		if (key === 'price') return b.newPrice - a.newPrice;
		if (ua) return a.listingId - b.listingId;
		if (key === 'abs') return Math.abs(b.change!) - Math.abs(a.change!) || a.listingId - b.listingId;
		return (b.pctChange ?? 0) - (a.pctChange ?? 0) || a.listingId - b.listingId;
	});
}

// Column-header sort layer (movers/+page.svelte): re-orders whatever set the
// Abs/Pct/Price controls produced. `sortRows` (see $lib/tableSort) only pins
// a literal `null` last, so any column that carries a "movement" value —
// currently just Change — must itself return null for an unknown row rather
// than the row's raw (and possibly non-null) value, or `sortRows` will sort
// it in among real movers.
export type ColSortKey = 'old' | 'new' | 'change' | 'points';

export function moverColumnValue(m: Mover, key: ColSortKey): string | number | null {
	if (key === 'old') return m.oldPrice;
	if (key === 'new') return m.newPrice;
	if (key === 'change') return isUnknownMover(m) ? null : m.change;
	return m.historyPoints;
}

export type MoverDirFilter = 'all' | 'up' | 'down';

// The /movers view that lives in the URL, so a shared link reproduces it (#26).
export interface MoverView {
	sort: MoverSortKey;
	dir: MoverDirFilter;
	group: boolean;
}

// Anything unrecognised (a hand-edited or stale link) degrades to the default.
export function parseMoverView(params: URLSearchParams): MoverView {
	const sort = params.get('sort');
	const dir = params.get('dir');
	return {
		sort: sort === 'pct' || sort === 'price' ? sort : 'abs',
		dir: dir === 'up' || dir === 'down' ? dir : 'all',
		group: params.get('group') !== '0'
	};
}

// Default keys are omitted, so the plain /movers?window=7d stays plain.
export function moversHref(window: string, view: MoverView, showAll: boolean): string {
	const p = new URLSearchParams({ window });
	if (view.sort !== 'abs') p.set('sort', view.sort);
	if (view.dir !== 'all') p.set('dir', view.dir);
	if (!view.group) p.set('group', '0');
	if (showAll) p.set('all', '1');
	return `?${p.toString()}`;
}

export interface MoverGroup {
	productId: number;
	lead: Mover;
	rest: Mover[];
}

// One entry per product, in the order given (#5 item 4). `ordered` is already
// sorted by the Sort control and any column sort, so a product's first row is
// its best under that order and groups follow their leads -- grouping can never
// disagree with the sort. Builds new arrays: the input is memo-shared.
export function groupMoversByProduct(ordered: readonly Mover[]): MoverGroup[] {
	const byProduct = new Map<number, MoverGroup>();
	for (const m of ordered) {
		const g = byProduct.get(m.productId);
		if (g) g.rest.push(m);
		else byProduct.set(m.productId, { productId: m.productId, lead: m, rest: [] });
	}
	return [...byProduct.values()];
}
