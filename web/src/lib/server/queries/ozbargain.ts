import type { DB } from '../db';
import type { OzbDeal } from '../../models';
import { cheapestListingPerProduct } from './sql';

// OzBargain deals matched to products (#34). ozb_deals is written by the
// Python pipeline every 2 hours; an older DB may not have the table yet, which
// is "no deals", never an error.
//
// Timestamps carry an offset (+10:00 / +11:00), so they are compared as
// instants in JS, never as strings in SQL: across a DST change the strings
// do not sort in time order.

const LIVE_CAP = 5;
const EXPIRED_CAP = 10;
const EXPIRED_WINDOW_MS = 30 * 24 * 3_600_000;

interface Row {
	nodeId: number;
	title: string;
	url: string;
	priceAud: number | null;
	retailer: string | null;
	votesPos: number;
	votesNeg: number;
	postedAt: string | null;
	startsAt: string | null;
	expired: number;
	productId: number | null;
	firstSeenAt: string;
	lastSeenAt: string;
}

const COLUMNS = `node_id AS nodeId, title, url, price_aud AS priceAud, retailer,
	votes_pos AS votesPos, votes_neg AS votesNeg, posted_at AS postedAt, starts_at AS startsAt,
	expired, product_id AS productId, first_seen_at AS firstSeenAt, last_seen_at AS lastSeenAt`;

function rows(db: DB, where: string, ...params: unknown[]): Row[] {
	try {
		return db.prepare(`SELECT ${COLUMNS} FROM ozb_deals WHERE ${where}`).all(...params) as Row[];
	} catch {
		return [];
	}
}

function ms(iso: string | null): number {
	if (!iso) return Number.NaN;
	return new Date(iso).getTime();
}

// "Live" is the alert rule's: not expired, and started (or no start date).
function isLive(r: Row, now: Date): boolean {
	if (r.expired) return false;
	if (r.startsAt === null) return true;
	const start = ms(r.startsAt);
	return Number.isNaN(start) || start <= now.getTime();
}

function toDeal(r: Row): OzbDeal {
	return {
		nodeId: r.nodeId,
		title: r.title,
		url: r.url,
		priceAud: r.priceAud,
		retailer: r.retailer,
		votesPos: r.votesPos,
		votesNeg: r.votesNeg,
		postedAt: r.postedAt,
		expired: r.expired !== 0
	};
}

// Newest first by an instant; unparseable values sort last, node id breaks ties.
function newestFirst(at: (r: Row) => number) {
	return (a: Row, b: Row) => {
		const x = at(a);
		const y = at(b);
		const xs = Number.isNaN(x) ? -Infinity : x;
		const ys = Number.isNaN(y) ? -Infinity : y;
		return ys - xs || b.nodeId - a.nodeId;
	};
}

export function getOzbDeals(
	db: DB,
	productId: number,
	now: Date
): { live: OzbDeal[]; expired: OzbDeal[] } {
	const all = rows(db, 'product_id = ?', productId);
	const live = all
		.filter((r) => isLive(r, now))
		.sort(newestFirst((r) => ms(r.postedAt ?? r.firstSeenAt)))
		.slice(0, LIVE_CAP)
		.map(toDeal);
	const since = now.getTime() - EXPIRED_WINDOW_MS;
	const expired = all
		.filter((r) => r.expired && ms(r.lastSeenAt) >= since)
		.sort(newestFirst((r) => ms(r.lastSeenAt)))
		.slice(0, EXPIRED_CAP)
		.map(toDeal);
	return { live, expired };
}

// The cheapest live, priced deal per product, for the /deals chip.
export function getLiveOzbDealByProduct(db: DB, now: Date = new Date()): Map<number, OzbDeal> {
	const best = new Map<number, Row>();
	for (const r of rows(db, 'product_id IS NOT NULL AND expired = 0 AND price_aud IS NOT NULL')) {
		if (!isLive(r, now)) continue;
		const pid = r.productId as number;
		const cur = best.get(pid);
		if (!cur || (r.priceAud as number) < (cur.priceAud as number)) best.set(pid, r);
	}
	return new Map([...best].map(([pid, r]) => [pid, toDeal(r)]));
}

// "Below our best" uses the Python alert's rule (R1/R7): the cheapest in-stock,
// non-bundle price on an ACTIVE listing on the GLOBAL latest snapshot date --
// cheapestListingPerProduct, not a second spelling of it. null = no best.
export function getBestInStockPrice(db: DB, productId: number): number | null {
	const row = db
		.prepare(cheapestListingPerProduct('ps.price_aud AS price', 'p.id = ?'))
		.get(productId) as { price: number } | undefined;
	return row?.price ?? null;
}
