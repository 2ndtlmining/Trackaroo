// The /products catalogue's columns (#23). The header row and every
// ProductRow read their widths and breakpoints from here, so a column cannot
// drift out of line with its label.
import type { CatalogSort } from './catalogView';
import type { Category } from './types';

export const COL = {
	// -mx-2: the row's padded compare label overhangs its cell (ProductRow).
	compare: '-mx-2 w-14 shrink-0',
	price: 'w-24 shrink-0',
	// basis-32: at lg the row also carries the vs-MSRP column, and a wider
	// basis would wrap the model onto its own line there.
	model: 'min-w-0 flex-1 basis-32',
	spec: 'hidden w-16 shrink-0 text-right md:block',
	socket: 'hidden w-16 shrink-0 xl:block',
	threads: 'hidden w-14 shrink-0 text-right xl:block',
	released: 'hidden w-20 shrink-0 md:block',
	listings: 'hidden w-20 shrink-0 text-right md:block',
	trend: 'hidden w-14 shrink-0 lg:block',
	range: 'hidden w-24 shrink-0 xl:block',
	value: 'hidden w-14 shrink-0 text-right xl:block',
	brand: 'hidden w-20 shrink-0 xl:flex',
	delta: 'w-36 shrink-0',
	msrp: 'hidden w-16 shrink-0 text-right lg:block',
	// xl-only narrowing: the xl row has no room (the value column), below it there is.
	retailer: 'w-20 xl:w-16 shrink-0 truncate whitespace-nowrap text-right'
} as const;

export interface CatalogColumn {
	key: keyof typeof COL;
	label: string;
	sort?: CatalogSort;
}

// Socket and threads are CPU-only; brand is GPU-only and from xl, since CPU
// names already say Ryzen or Core and the CPU row has no room for it.
export function catalogColumns(category: Category, priceAt: string | null): CatalogColumn[] {
	const cpu = category === 'cpu';
	return [
		{ key: 'compare', label: 'Compare' },
		{ key: 'price', label: priceAt ? `Price at ${priceAt}` : 'Price', sort: 'price' },
		{ key: 'model', label: 'Model', sort: 'name' },
		{ key: 'spec', label: cpu ? 'Cores' : 'VRAM', sort: 'spec' },
		...(cpu
			? [
					{ key: 'socket', label: 'Socket' } as CatalogColumn,
					{ key: 'threads', label: 'Threads' } as CatalogColumn
				]
			: []),
		{ key: 'released', label: 'Released', sort: 'released' },
		{ key: 'listings', label: 'Listings', sort: 'listings' },
		{ key: 'trend', label: '30-day' },
		{ key: 'range', label: '90-day range' },
		{ key: 'value', label: 'Perf/A$1k', sort: 'value' },
		...(cpu ? [] : [{ key: 'brand', label: 'Brand' } as CatalogColumn]),
		{ key: 'delta', label: 'vs average' },
		{ key: 'msrp', label: 'vs MSRP', sort: 'msrp' },
		{ key: 'retailer', label: 'Retailer' }
	];
}
