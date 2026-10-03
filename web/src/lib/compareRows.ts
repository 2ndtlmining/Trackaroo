import { formatAud, formatBandwidth, formatCacheMb, formatDate, formatProcess, formatUsd } from './formats';
import { retailerLabel } from './filters';
import type { CompareEntry } from './models';
import { METRICS, defaultMetric, perfFor, sourceNote } from './perfIndex';
import type { Retailer } from './types';
import { perfPerKilo } from './value';

export interface CompareRow {
	label: string;
	value: (entry: CompareEntry) => string | null;
	// Absent = neutral: the row never marks a best value.
	direction?: 'higher' | 'lower';
	// The comparable number behind `value`; read from the same field.
	numeric?: (entry: CompareEntry) => number | null;
	// Set in the mono tabular face (#22); rows with `numeric` always are.
	mono?: boolean;
	// What the figure means, shown on hover and read by screen readers.
	hint?: string;
}

// Mirrors the value formatters, which treat 0 as missing.
function positive(n: number | null | undefined): number | null {
	return n ? n : null;
}

// Indexes of the entries holding the best value in a row. Ties mark every tied
// entry; fewer than two numeric values, or all equal, marks none.
export function bestIndexes(row: CompareRow, entries: CompareEntry[]): Set<number> {
	if (!row.direction || !row.numeric) return new Set();
	const nums = entries.map((e) => row.numeric!(e));
	const present = nums.filter((n): n is number => n !== null && Number.isFinite(n));
	if (present.length < 2) return new Set();
	const best = row.direction === 'higher' ? Math.max(...present) : Math.min(...present);
	if (present.every((n) => n === best)) return new Set();
	const out = new Set<number>();
	nums.forEach((n, i) => {
		if (n === best) out.add(i);
	});
	return out;
}

export function clock(mhz: number | null): string | null {
	return mhz === null ? null : `${(mhz / 1000).toFixed(1)} GHz`;
}

// Fixed locale: a bare toLocaleString() follows the viewer's machine, so the
// server ("4,608") and a German browser ("4.608") would disagree on hydration.
const CORE_FORMAT = new Intl.NumberFormat('en-AU');

const sharedSpecRows: CompareRow[] = [
	{
		label: 'US launch MSRP',
		mono: true,
		value: (e) => (e.spec?.launch_msrp_usd ? formatUsd(e.spec.launch_msrp_usd) : null)
	},
	{
		label: 'Launch date',
		value: (e) => (e.spec?.launch_date ? formatDate(e.spec.launch_date) : null)
	},
	{
		label: 'Architecture',
		value: (e) => e.spec?.architecture ?? null
	},
	{
		label: 'Generation',
		// Match the product-detail panel: some sources (Intel CSVs) carry the
		// generation under `architecture` only, so fall back to it rather than
		// rendering N/A for genuinely-populated data.
		value: (e) => e.spec?.generation ?? e.spec?.architecture ?? null
	},
	{
		label: 'TDP',
		direction: 'lower',
		numeric: (e) => positive(e.spec?.tdp_watts),
		value: (e) => (e.spec?.tdp_watts ? `${e.spec.tdp_watts} W` : null)
	}
];

const gpuSpecRows: CompareRow[] = [
	{
		label: 'GPU die',
		value: (e) => e.spec?.gpu_die ?? null
	},
	{
		label: 'VRAM',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.vram_gb),
		value: (e) => (e.spec?.vram_gb ? `${e.spec.vram_gb}GB` : null)
	},
	{
		label: 'Memory type',
		value: (e) => e.spec?.memory_type ?? null
	},
	{
		label: 'Memory bus',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.memory_bus_width_bit),
		value: (e) => (e.spec?.memory_bus_width_bit ? `${e.spec.memory_bus_width_bit}-bit` : null)
	},
	{
		label: 'Bandwidth',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.memory_bandwidth_gbps),
		value: (e) => formatBandwidth(e.spec?.memory_bandwidth_gbps ?? null)
	},
	{
		label: 'Bus interface',
		value: (e) => e.spec?.bus_interface ?? null
	},
	{
		label: 'Process',
		direction: 'lower',
		numeric: (e) => positive(e.spec?.process_nm),
		value: (e) => formatProcess(e.spec?.process_nm ?? null, e.spec?.foundry ?? null)
	},
	{
		label: 'L2 cache',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.l2_cache_mb),
		value: (e) => formatCacheMb(e.spec?.l2_cache_mb ?? null)
	},
	{
		label: 'Base clock',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.base_clock_mhz),
		value: (e) => clock(e.spec?.base_clock_mhz ?? null)
	},
	{
		label: 'Boost clock',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.boost_clock_mhz),
		value: (e) => clock(e.spec?.boost_clock_mhz ?? null)
	}
];

const cpuSpecRows: CompareRow[] = [
	{
		label: 'Cores / shaders',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.core_count),
		value: (e) => (e.spec?.core_count ? CORE_FORMAT.format(e.spec.core_count) : null)
	},
	{
		label: 'Threads',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.thread_count),
		value: (e) => (e.spec?.thread_count ? String(e.spec.thread_count) : null)
	},
	{
		label: 'Codename',
		value: (e) => e.spec?.codename ?? null
	},
	{
		label: 'Base clock',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.base_clock_mhz),
		value: (e) => clock(e.spec?.base_clock_mhz ?? null)
	},
	{
		label: 'Boost clock',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.boost_clock_mhz),
		value: (e) => clock(e.spec?.boost_clock_mhz ?? null)
	},
	{
		label: 'Socket',
		value: (e) => e.spec?.socket ?? null
	},
	{
		label: 'L3 cache',
		value: (e) => formatCacheMb(e.spec?.cache_l3_mb ?? null)
	},
	{
		label: 'L2 cache',
		direction: 'higher',
		numeric: (e) => positive(e.spec?.l2_cache_mb),
		value: (e) => formatCacheMb(e.spec?.l2_cache_mb ?? null)
	},
	{
		label: 'Memory support',
		value: (e) => e.spec?.memory_types ?? null
	},
	{
		label: 'Max memory speed',
		value: (e) => (e.spec?.memory_speed_mhz ? `${e.spec.memory_speed_mhz} MHz` : null)
	}
];

// Performance per A$1,000 at the cheapest in-stock price (#33), on the
// category's default metric; a dash when either figure is missing.
function perPerfRow(category: 'gpu' | 'cpu'): CompareRow {
	const metric = defaultMetric(category);
	const numeric = (e: CompareEntry) =>
		perfPerKilo(
			e.cheapestInStock?.price ?? null,
			perfFor({ category, model: e.product.model, vramGb: e.product.vram_gb }, metric)
		);
	return {
		label: 'Perf / A$1k',
		direction: 'higher',
		hint: `per A$1,000, ${METRICS[metric].label}. ${sourceNote(metric)}`,
		numeric,
		value: (e) => {
			const n = numeric(e);
			return n === null ? '–' : String(Math.round(n));
		}
	};
}

// Compare rows are category-aware: the server route guarantees all entries are
// the same category, so a single category check decides which spec fields make
// sense. GPU-only and CPU-only rows never show for the wrong category.
export function buildCompareRows(entries: CompareEntry[]): CompareRow[] {
	const retailers = [
		...new Set<Retailer>(entries.flatMap((e) => e.prices.map((p) => p.retailer)))
	].sort((a, b) => a.localeCompare(b));

	const priceRows: CompareRow[] = [
		...retailers.map(
			(r): CompareRow => ({
				label: `Best price — ${retailerLabel(r)}`,
				direction: 'lower',
				numeric: (e) => e.prices.find((x) => x.retailer === r)?.price ?? null,
				value: (e) => {
					const p = e.prices.find((x) => x.retailer === r);
					return p?.price !== undefined && p.price !== null ? formatAud(p.price) : null;
				}
			})
		),
		{
			label: 'Cheapest in stock',
			direction: 'lower',
			numeric: (e) => e.cheapestInStock?.price ?? null,
			value: (e) =>
				e.cheapestInStock
					? `${formatAud(e.cheapestInStock.price)} · ${retailerLabel(e.cheapestInStock.retailer)}`
					: null
		}
	];

	const category = entries[0]?.product.category;
	const perfRows: CompareRow[] =
		category === 'gpu' || category === 'cpu' ? [perPerfRow(category)] : [];
	const specRows =
		category === 'gpu' ? gpuSpecRows : category === 'cpu' ? cpuSpecRows : sharedSpecRows;

	return [...priceRows, ...perfRows, ...sharedSpecRows, ...specRows];
}