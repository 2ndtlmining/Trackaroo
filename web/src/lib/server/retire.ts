// Ready-to-retire suggestions (#17): reads retire_suggestions (written daily by
// retire_suggest.py) and records Retire / Keep / Undo decisions. Like discover.ts,
// every reader tolerates a DB that predates the table.
import type { DB } from './db';
import type { RetireAction, RetireDecision, RetireSuggestion } from '$lib/types';

// Mirrors config.RETIRE_KEEP_DAYS in the Python side (TS cannot read it).
const KEEP_DAYS = 90;

const ACTIONS: Record<RetireAction, { from: RetireDecision[]; to: RetireDecision }> = {
	retire: { from: ['pending'], to: 'requested' },
	keep: { from: ['pending'], to: 'kept' },
	undo: { from: ['requested', 'kept'], to: 'pending' }
};

export function isRetireAction(value: unknown): value is RetireAction {
	return typeof value === 'string' && Object.hasOwn(ACTIONS, value);
}

function hasTable(db: DB): boolean {
	const row = db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = 'retire_suggestions'").get() as {
		n: number;
	};
	return row.n === 1;
}

interface Row {
	product_id: number;
	brand: string;
	category: 'cpu' | 'gpu';
	model: string;
	first_flagged: string;
	last_seen: string | null;
	last_seen_retailer: string | null;
	decision: RetireDecision;
	keep_until: string | null;
}

// Kept rows stay hidden while keep_until is still in the future; once it
// passes they show again as a fresh suggestion.
export function getRetireSuggestions(db: DB, today: string): RetireSuggestion[] {
	if (!hasTable(db)) return [];
	const rows = db
		.prepare(
			`SELECT r.product_id, p.brand, p.category, p.model, r.first_flagged, r.last_seen,
			        r.last_seen_retailer, r.decision, r.keep_until
			 FROM retire_suggestions r JOIN products p ON p.id = r.product_id
			 WHERE r.decision != 'kept' OR r.keep_until IS NULL OR r.keep_until <= ?
			 ORDER BY (r.decision = 'requested'), p.model`
		)
		.all(today) as Row[];
	return rows.map((r) => ({
		productId: r.product_id,
		brand: r.brand,
		category: r.category,
		model: r.model,
		firstFlagged: r.first_flagged,
		lastSeen: r.last_seen,
		lastSeenRetailer: r.last_seen_retailer,
		decision: r.decision,
		keepUntil: r.keep_until
	}));
}

export function applyRetireAction(
	db: DB,
	productId: number,
	action: RetireAction,
	today: string
): 'ok' | 'not-found' | 'invalid' {
	if (!hasTable(db)) return 'not-found';
	const row = db.prepare('SELECT decision FROM retire_suggestions WHERE product_id = ?').get(productId) as
		| { decision: RetireDecision }
		| undefined;
	if (!row) return 'not-found';
	const rule = ACTIONS[action];
	if (!rule.from.includes(row.decision)) return 'invalid';
	const marks = rule.from.map(() => '?').join(', ');
	const keepUntil = action === 'keep' ? `date(?, '+${KEEP_DAYS} days')` : 'NULL';
	const params: unknown[] = [rule.to];
	if (action === 'keep') params.push(today);
	params.push(productId, ...rule.from);
	const res = db
		.prepare(`UPDATE retire_suggestions SET decision = ?, keep_until = ${keepUntil} WHERE product_id = ? AND decision IN (${marks})`)
		.run(...params);
	return res.changes === 0 ? 'invalid' : 'ok';
}
