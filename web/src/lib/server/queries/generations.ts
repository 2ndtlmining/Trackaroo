// Series labels per product line, from the generations table seed.py mirrors
// out of db/generations.toml (#17). A launch or relabel needs no web rebuild.
import type { DB } from '../db';
import type { GenerationTier } from '$lib/types';
import type { TierLabels } from '$lib/models';

const TIERS: GenerationTier[] = ['current', 'current-1', 'current-2'];

export function getTierLabels(db: DB): TierLabels {
	const has = db
		.prepare("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'generations'")
		.get();
	if (!has) return {};
	const rows = db
		.prepare('SELECT line_id, label, position FROM generations WHERE position < 3 ORDER BY line_id, position')
		.all() as { line_id: string; label: string; position: number }[];
	const out: TierLabels = {};
	for (const r of rows) (out[r.line_id] ??= {})[TIERS[r.position]] = r.label;
	return out;
}
