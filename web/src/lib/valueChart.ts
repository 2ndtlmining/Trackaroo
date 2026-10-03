// Pure helpers behind the /value scatter and budget cards (#33). No DOM, so
// the axis maths and the copy are pinned by tests.

export interface NiceScale {
	max: number;
	ticks: number[];
}

const STEPS = [1, 2, 2.5, 5, 10];

/** A 0-based axis whose top is the first clean step at or above `value`. */
export function niceScale(value: number, target = 5): NiceScale {
	const v = Number.isFinite(value) && value > 0 ? value : 1;
	const raw = v / target;
	const mag = 10 ** Math.floor(Math.log10(raw));
	const step = (STEPS.find((s) => s * mag >= raw) ?? 10) * mag;
	const n = Math.ceil(v / step - 1e-9);
	const ticks = Array.from({ length: n + 1 }, (_, i) => Number((i * step).toPrecision(12)));
	return { max: ticks[ticks.length - 1], ticks };
}

export interface NiceRange {
	lo: number;
	hi: number;
	ticks: number[];
}

/**
 * The performance axis. From 0 when the data spreads widely (GPUs, 15 to 93),
 * but CPUs cluster within 25% of each other (89 to 113), and a 0 baseline
 * would flatten them into one line. This is a scatter, not bars, so a
 * clipped baseline misstates no length.
 */
export function niceRange(min: number, max: number, target = 5): NiceRange {
	const top = niceScale(max, target);
	if (!(Number.isFinite(min) && min > top.max * 0.5)) return { lo: 0, hi: top.max, ticks: top.ticks };
	const span = Math.max(max - min, max * 0.05);
	const raw = span / target;
	const mag = 10 ** Math.floor(Math.log10(raw));
	const step = (STEPS.find((s) => s * mag >= raw) ?? 10) * mag;
	const lo = Math.floor(min / step - 1e-9) * step - (min % step === 0 ? step : 0);
	const hi = Math.ceil(max / step - 1e-9) * step;
	const ticks: number[] = [];
	for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Number(t.toPrecision(12)));
	return { lo: ticks[0], hi: ticks[ticks.length - 1], ticks };
}

export interface LogScale {
	lo: number;
	hi: number;
	ticks: number[];
}

/**
 * A log price axis. Prices run from about $150 to $7,000+, and on a linear
 * axis one flagship squeezes every card a buyer is choosing between into the
 * left fifth. Dominance survives any monotone axis, so the frontier is the
 * same. Ticks are 1-2-5 per decade, or finer steps when the range is under a
 * decade (CPUs) so there are always a few.
 */
export function logScale(min: number, max: number): LogScale {
	const a = Number.isFinite(min) && min > 0 ? min : 100;
	const b = Number.isFinite(max) && max >= a ? max : a;
	const lo = a / 1.15;
	const hi = b * 1.15;
	const mantissas = hi / lo < 12 ? [1, 1.5, 2, 3, 4, 5, 7] : [1, 2, 5];
	const ticks: number[] = [];
	for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
		for (const m of mantissas) {
			const t = Number((m * 10 ** e).toPrecision(12));
			if (t >= lo && t <= hi) ticks.push(t);
		}
	}
	return { lo, hi, ticks };
}

/**
 * The frontier as a staircase (step-after): from each point across to the
 * next price, then up to that point's performance. Read left to right it is
 * the best performance money can buy at each price. Points must be price ascending.
 */
export function stepPath(points: { x: number; y: number }[]): string {
	if (points.length === 0) return '';
	const r = (n: number) => Math.round(n * 10) / 10;
	let d = `M${r(points[0].x)},${r(points[0].y)}`;
	for (const p of points.slice(1)) d += `H${r(p.x)}V${r(p.y)}`;
	return d;
}

/** "GeForce RTX 5060 Ti" -> "RTX 5060 Ti": chart labels drop the family name. */
export function shortName(name: string): string {
	return name.replace(/^(GeForce|Radeon)\s+/, '');
}

/** "12% faster than the runner-up"; null when there is no runner-up. */
export function gapLabel(gap: number | null): string | null {
	if (gap == null || !Number.isFinite(gap)) return null;
	const pct = Math.round(gap * 100);
	return pct <= 0 ? 'Level with the runner-up' : `${pct}% faster than the runner-up`;
}

/** Perf per A$1,000 as a whole number, or the no-data dash. */
export function kiloLabel(v: number | null): string {
	return v == null || !Number.isFinite(v) ? '–' : String(Math.round(v));
}

/** "$1.2k" style tick labels: short enough for a 320 px axis. */
export function audTick(v: number): string {
	if (v === 0) return '$0';
	if (v >= 1000) return `$${Number((v / 1000).toFixed(2))}k`;
	return `$${v}`;
}
