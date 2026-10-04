// Head-to-head matchup for the product page (#60). Prices come from
// getValueRows (the one price rule, #59); the rules live in $lib/matchups.
import type { DB } from '../db';
import { getValueRows } from './value';
import { perfFor } from '../../perfIndex';
import { perfPerKilo } from '../../value';
import { buildDisplayNames } from '../../displayName';
import {
	LINE_METRICS,
	MAIN_METRIC,
	findRival,
	matchupLines,
	type MatchupCandidate,
	type MatchupCategory
} from '../../matchups';
import type { Matchup, MatchupSide, ValueRow } from '../../models';

function toCandidate(r: ValueRow, category: MatchupCategory): MatchupCandidate {
	const scores: MatchupCandidate['scores'] = {};
	for (const metric of LINE_METRICS[category]) {
		const v = perfFor({ category, model: r.model, vramGb: r.vramGb }, metric);
		if (v !== null) scores[metric] = v;
	}
	return { id: r.id, brand: r.brand, model: r.model, vramGb: r.vramGb, tier: r.tier, price: r.price, scores };
}

export function getMatchup(db: DB, productId: number): Matchup | null {
	const row = db.prepare('SELECT category FROM products WHERE id = ?').get(productId) as
		| { category: string }
		| undefined;
	if (!row || (row.category !== 'gpu' && row.category !== 'cpu')) return null;
	const category = row.category;

	const rows = getValueRows(db, category);
	const candidates = rows.map((r) => toCandidate(r, category));
	const p = candidates.find((c) => c.id === productId);
	if (!p) return null;
	const rival = findRival(p, candidates, category);
	if (!rival) return null;
	const lines = matchupLines(p, rival, category);
	if (lines.length === 0) return null;

	const metric = MAIN_METRIC[category];
	const names = buildDisplayNames(rows.map((r) => ({ id: r.id, category, model: r.model, vramGb: r.vramGb })));
	const side = (c: MatchupCandidate): MatchupSide => ({
		id: c.id,
		name: names.get(c.id) ?? c.model,
		// findRival only returns priced, scored candidates, and P passed the same checks.
		price: c.price as number,
		perfPerKilo: perfPerKilo(c.price, c.scores[metric] ?? null) as number
	});
	return { category, metric, product: side(p), rival: side(rival), lines };
}
