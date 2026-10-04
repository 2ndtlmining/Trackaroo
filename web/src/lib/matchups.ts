// Head-to-head matchups (#60): the nearest rival from the other brand and the
// cost-per-frame comparison per metric. Pure and client-safe: no I/O, no DB.
// Rules: docs/superpowers/specs/2026-10-04-matchups-design.md §2-§3.
import type { MetricKey } from './perfIndex';

export type MatchupCategory = 'gpu' | 'cpu';

export interface MatchupCandidate {
	id: number;
	brand: string;
	model: string;
	vramGb: number | null;
	tier: string | null;
	/** Today's price by the one price rule; null when not in stock. */
	price: number | null;
	scores: Partial<Record<MetricKey, number>>;
}

export type MatchupDirection = 'cheaper' | 'dearer' | 'same';

export interface MatchupLine {
	metric: MetricKey;
	direction: MatchupDirection;
	/** Whole percent; 0 when direction is 'same'. */
	pct: number;
}

// Intel GPUs are left out on purpose (owner decision, 4-Oct-2026).
const BRAND_PAIRS: Record<MatchupCategory, readonly [string, string]> = {
	gpu: ['NVIDIA', 'AMD'],
	cpu: ['AMD', 'Intel']
};

export const MAIN_METRIC: Record<MatchupCategory, MetricKey> = {
	gpu: 'gpu_raster_1440p',
	cpu: 'cpu_gaming_1080p'
};

export const LINE_METRICS: Record<MatchupCategory, MetricKey[]> = {
	gpu: ['gpu_raster_1440p', 'gpu_rt_1440p'],
	cpu: ['cpu_gaming_1080p']
};

const MAX_GAP = 0.15;
const VRAM_WINDOW = 3;
// "About the same" band, as literals so 98/100 compares equal to 0.98 exactly.
const CHEAPER_BELOW = 0.98;
const DEARER_ABOVE = 1.02;
const RIVAL_TIERS = new Set(['current', 'current-1']);
// Keeps an exact 15% gap inside the window despite float rounding.
const EPS = 1e-9;

function otherBrand(category: MatchupCategory, brand: string): string | null {
	const [a, b] = BRAND_PAIRS[category];
	if (brand === a) return b;
	if (brand === b) return a;
	return null;
}

function priced(c: MatchupCandidate): c is MatchupCandidate & { price: number } {
	return c.price !== null && Number.isFinite(c.price) && c.price > 0;
}

function score(c: MatchupCandidate, metric: MetricKey): number | null {
	const v = c.scores[metric];
	return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null;
}

export function findRival(
	p: MatchupCandidate,
	candidates: MatchupCandidate[],
	category: MatchupCategory
): MatchupCandidate | null {
	const rivalBrand = otherBrand(category, p.brand);
	const metric = MAIN_METRIC[category];
	const ps = score(p, metric);
	if (rivalBrand === null || ps === null || !priced(p)) return null;

	const pool: { c: MatchupCandidate & { price: number }; gap: number }[] = [];
	for (const c of candidates) {
		if (c.id === p.id || c.brand !== rivalBrand) continue;
		if (c.tier === null || !RIVAL_TIERS.has(c.tier) || !priced(c)) continue;
		const cs = score(c, metric);
		if (cs === null) continue;
		const gap = Math.abs(cs - ps);
		if (gap <= MAX_GAP * ps + EPS) pool.push({ c, gap });
	}
	if (pool.length === 0) return null;
	pool.sort((a, b) => a.gap - b.gap || a.c.price - b.c.price || a.c.id - b.c.id);

	const best = pool[0];
	if (category === 'gpu' && best.c.vramGb !== p.vramGb) {
		const same = pool.find((x) => x.c.vramGb === p.vramGb && x.gap - best.gap <= VRAM_WINDOW + EPS);
		if (same) return same.c;
	}
	return best.c;
}

export function matchupLines(
	p: MatchupCandidate,
	rival: MatchupCandidate,
	category: MatchupCategory
): MatchupLine[] {
	if (!priced(p) || !priced(rival)) return [];
	const lines: MatchupLine[] = [];
	for (const metric of LINE_METRICS[category]) {
		const ps = score(p, metric);
		const rs = score(rival, metric);
		if (ps === null || rs === null) continue;
		const r = p.price / ps / (rival.price / rs);
		if (r < CHEAPER_BELOW) lines.push({ metric, direction: 'cheaper', pct: Math.round((1 - r) * 100) });
		else if (r > DEARER_ABOVE) lines.push({ metric, direction: 'dearer', pct: Math.round((r - 1) * 100) });
		else lines.push({ metric, direction: 'same', pct: 0 });
	}
	return lines;
}
