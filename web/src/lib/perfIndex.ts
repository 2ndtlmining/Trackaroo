// Curated performance index (#33): relative % from published tables, one
// source per metric. Client-safe; the JSON is the same file the Python tests
// verify (db/perf_index.json), so no value here is ever typed by hand.
import index from '../../../db/perf_index.json';

export type MetricKey = 'gpu_raster_1440p' | 'gpu_rt_1440p' | 'cpu_gaming_1080p';

export interface MetricInfo {
	label: string;
	unit: string;
	source: string;
	source_url: string;
	as_of: string;
	baseline: string;
}

export interface PerfProduct {
	category: 'gpu' | 'cpu';
	model: string;
	vramGb: number | null;
}

export const METRICS = index.metrics as Record<MetricKey, MetricInfo>;
const PRODUCTS = index.products as Record<string, Partial<Record<MetricKey, number>>>;
const NOT_IN_SOURCE = index.not_in_source as Partial<Record<MetricKey, string[]>>;

/**
 * Index key (ruling R5). GPU: the model alone when it already ends with
 * " <vram>GB" (the 8 GB variants are separate watchlist rows named so),
 * otherwise "<model> <vram>GB". CPU: the model.
 */
export function perfKey(p: PerfProduct): string {
	if (p.category !== 'gpu' || p.vramGb == null) return p.model;
	const spec = `${p.vramGb}GB`;
	return p.model.endsWith(` ${spec}`) ? p.model : `${p.model} ${spec}`;
}

export function perfFor(p: PerfProduct, metric: MetricKey): number | null {
	const v = PRODUCTS[perfKey(p)]?.[metric];
	return typeof v === 'number' ? v : null;
}

/** True when the key is in the index, or declared absent from a source table. */
export function isIndexed(key: string): boolean {
	return key in PRODUCTS || Object.values(NOT_IN_SOURCE).some((l) => l?.includes(key));
}

export function defaultMetric(category: 'gpu' | 'cpu'): MetricKey {
	return category === 'gpu' ? 'gpu_raster_1440p' : 'cpu_gaming_1080p';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function asOfLabel(asOf: string): string {
	const m = /^(\d{4})-(\d{2})$/.exec(asOf);
	const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
	return m && month ? `${month} ${m[1]}` : asOf;
}

/** "1440p raster, TechPowerUp, <review title>, Apr 2026": the on-screen citation. */
export function sourceNote(metric: MetricKey): string {
	const m = METRICS[metric];
	// source reads "TechPowerUp, <review title> (<chart>)"; keep publisher and title.
	const cited = m.source.replace(/\s*\([^)]*\)\s*$/, '');
	return `${m.label}, ${cited}, ${asOfLabel(m.as_of)}`;
}
