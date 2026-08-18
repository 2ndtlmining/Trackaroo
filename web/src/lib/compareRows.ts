import { formatAud, formatDate, formatUsd } from './formats';
import type { CompareEntry } from './server/repos';
import type { Retailer } from './types';

export interface CompareRow {
	label: string;
	value: (entry: CompareEntry) => string | null;
}

export function clock(mhz: number | null): string | null {
	return mhz === null ? null : `${(mhz / 1000).toFixed(1)} GHz`;
}

const sharedSpecRows: CompareRow[] = [
	{
		label: 'Launch MSRP (USD)',
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
		value: (e) => (e.spec?.tdp_watts ? `${e.spec.tdp_watts} W` : null)
	}
];

const gpuSpecRows: CompareRow[] = [
	{
		label: 'VRAM',
		value: (e) => (e.spec?.vram_gb ? `${e.spec.vram_gb}GB` : null)
	},
	{
		label: 'Memory type',
		value: (e) => e.spec?.memory_type ?? null
	},
	{
		label: 'Memory bus',
		value: (e) => (e.spec?.memory_bus_width_bit ? `${e.spec.memory_bus_width_bit}-bit` : null)
	},
	{
		label: 'Base clock',
		value: (e) => clock(e.spec?.base_clock_mhz ?? null)
	},
	{
		label: 'Boost clock',
		value: (e) => clock(e.spec?.boost_clock_mhz ?? null)
	}
];

const cpuSpecRows: CompareRow[] = [
	{
		label: 'Cores / shaders',
		value: (e) => (e.spec?.core_count ? e.spec.core_count.toLocaleString() : null)
	},
	{
		label: 'Threads',
		value: (e) => (e.spec?.thread_count ? String(e.spec.thread_count) : null)
	},
	{
		label: 'Base clock',
		value: (e) => clock(e.spec?.base_clock_mhz ?? null)
	},
	{
		label: 'Boost clock',
		value: (e) => clock(e.spec?.boost_clock_mhz ?? null)
	},
	{
		label: 'Socket',
		value: (e) => e.spec?.socket ?? null
	},
	{
		label: 'L3 cache',
		value: (e) => (e.spec?.cache_l3_mb ? `${e.spec.cache_l3_mb} MB` : null)
	}
];

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
				label: `Best price — ${r}`,
				value: (e) => {
					const p = e.prices.find((x) => x.retailer === r);
					return p?.price !== undefined && p.price !== null ? formatAud(p.price) : null;
				}
			})
		),
		{
			label: 'Cheapest in stock',
			value: (e) =>
				e.cheapestInStock
					? `${formatAud(e.cheapestInStock.price)} · ${e.cheapestInStock.retailer}`
					: null
		}
	];

	const category = entries[0]?.product.category;
	const specRows =
		category === 'gpu' ? gpuSpecRows : category === 'cpu' ? cpuSpecRows : sharedSpecRows;

	return [...priceRows, ...sharedSpecRows, ...specRows];
}