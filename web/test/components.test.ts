import { describe, expect, it, vi } from 'vitest';
import { mount, tick, unmount } from 'svelte';
import Badge from '../src/lib/components/Badge.svelte';
import BrandIcon from '../src/lib/components/BrandIcon.svelte';
import CommandPalette from '../src/lib/components/CommandPalette.svelte';
import StatTile from '../src/lib/components/StatTile.svelte';
import PriceChange from '../src/lib/components/PriceChange.svelte';
import StockBadge from '../src/lib/components/StockBadge.svelte';
import Chip from '../src/lib/components/Chip.svelte';
import LatestListingTable from '../src/lib/components/LatestListingTable.svelte';
import ProductCard from '../src/lib/components/ProductCard.svelte';
import SpecPanel from '../src/lib/components/SpecPanel.svelte';
import BrandGroupedListings from '../src/lib/components/BrandGroupedListings.svelte';
	import CheapestCarousel from '../src/lib/components/CheapestCarousel.svelte';
	import Sparkline from '../src/lib/components/Sparkline.svelte';
	import type { LatestListing, ProductGroup, Series, CheapestListing, SparklinePoint } from '../src/lib/server/repos';
import type { ListingRow, SpecRow, SnapshotRow } from '../src/lib/server/db';

function renderComponent(Component: unknown, props: Record<string, unknown> = {}): string {
	const target = document.createElement('div');
	const comp = mount(Component as never, { target, props });
	const html = target.innerHTML;
	unmount(comp);
	return html;
}

function latestListing(overrides: Partial<LatestListing> = {}): LatestListing {
	return {
		listingId: 1,
		productId: 1,
		category: 'cpu',
		brand: 'AMD',
		model: 'Ryzen 5 7600',
		productVariant: null,
		generationTier: 'current',
		retailer: 'scorptec',
		variantName: 'Ryzen 5 7600, Tray, 65W',
		listingUrl: 'https://example.com/1',
		status: 'active',
		lastSnapshotAt: '2026-08-15T08:00:00Z',
		latestDate: '2026-08-15',
		latestPrice: 299,
		latestStock: 'in_stock',
		latestScrapedAt: '2026-08-15T08:00:00Z',
		windowStartDate: '2026-08-08',
		windowStartPrice: 319,
		pointsInWindow: 7,
		...overrides
	};
}

describe('Badge', () => {
	it('renders a dot and label', () => {
		const body = renderComponent(Badge, { label: 'In stock', tone: 'accent' });
		expect(body).toContain('In stock');
		expect(body).toContain('bg-accent');
	});

	it('applies the up tone dot', () => {
		const body = renderComponent(Badge, { label: '+5%', tone: 'up' });
		expect(body).toContain('bg-up');
		expect(body).toContain('text-up');
	});
});

describe('BrandIcon', () => {
	it('renders an svg with the brand color for a known brand', () => {
		const body = renderComponent(BrandIcon, { brand: 'AMD' });
		expect(body).toContain('<svg');
		expect(body).toContain('<path');
		expect(body).toContain('fill="#ED1C24"');
		expect(body).toContain('aria-label="AMD"');
	});

	it('renders the NVIDIA and Intel colors', () => {
		expect(renderComponent(BrandIcon, { brand: 'NVIDIA' })).toContain('fill="#76B900"');
		expect(renderComponent(BrandIcon, { brand: 'Intel' })).toContain('fill="#0071C5"');
	});

	it('renders nothing for an unknown brand', () => {
		const body = renderComponent(BrandIcon, { brand: 'PNY' });
		expect(body).not.toContain('<svg');
		expect(body).not.toContain('fill=');
	});

	it('respects the size prop', () => {
		const body = renderComponent(BrandIcon, { brand: 'AMD', size: 24 });
		expect(body).toContain('width="24"');
		expect(body).toContain('height="24"');
	});
});

describe('StatTile', () => {
	it('renders label and value', () => {
		const body = renderComponent(StatTile, { label: 'Listings', value: '315' });
		expect(body).toContain('Listings');
		expect(body).toContain('315');
	});

	it('renders sub when provided and omits it otherwise', () => {
		expect(renderComponent(StatTile, { label: 'L', value: '1', sub: '13 Aug' })).toContain(
			'13 Aug'
		);
		expect(renderComponent(StatTile, { label: 'L', value: '1' })).not.toContain('13 Aug');
	});
});

describe('PriceChange', () => {
	it('maps insufficient direction to the stale tone', () => {
		const body = renderComponent(PriceChange, { direction: 'insufficient', label: 'New listing' });
		expect(body).toContain('bg-stale');
	});

	it('maps up/down/flat tones', () => {
		expect(renderComponent(PriceChange, { direction: 'up', label: '+1%' })).toContain('bg-up');
		expect(renderComponent(PriceChange, { direction: 'down', label: '−1%' })).toContain('bg-down');
		expect(renderComponent(PriceChange, { direction: 'flat', label: '0%' })).toContain('bg-flat');
	});
});

describe('StockBadge', () => {
	it('renders the human stock label for each status', () => {
		expect(renderComponent(StockBadge, { stock: 'in_stock' })).toContain('In stock');
		expect(renderComponent(StockBadge, { stock: 'out_of_stock' })).toContain('Out of stock');
		expect(renderComponent(StockBadge, { stock: 'preorder' })).toContain('Preorder');
		expect(renderComponent(StockBadge, { stock: 'unknown' })).toContain('Unknown');
	});
});

describe('Chip', () => {
	it('renders label and value', () => {
		const body = renderComponent(Chip, { label: 'Category', value: 'gpu' });
		expect(body).toContain('Category');
		expect(body).toContain('gpu');
	});
});

describe('LatestListingTable', () => {
	it('shows an empty state when there are no rows', () => {
		const body = renderComponent(LatestListingTable, { rows: [] });
		expect(body).toContain('No listings match the current filters.');
	});

	it('renders model, price and stock for a populated row', () => {
		const body = renderComponent(LatestListingTable, { rows: [latestListing()] });
		expect(body).toContain('Ryzen 5 7600');
		expect(body).toContain('AMD');
		expect(body).toContain('scorptec');
		expect(body).toContain('299');
		expect(body).toContain('In stock');
	});

	it('truncates comma-separated variant names to the first segment', () => {
		const body = renderComponent(LatestListingTable, { rows: [latestListing()] });
		expect(body).toContain('>Ryzen 5 7600</td>');
		expect(body).toContain('title="Ryzen 5 7600, Tray, 65W"');
	});

	it('labels a brand-NEW listing rather than stale', () => {
		const row = latestListing({
			windowStartPrice: null,
			pointsInWindow: 1,
			lastSnapshotAt: null
		});
		const body = renderComponent(LatestListingTable, { rows: [row] });
		expect(body).toContain('New listing');
		expect(body).not.toContain('No data in window');
	});

	it('labels an old listing as stale with "last seen" freshness wording', () => {
		const row = latestListing({
			windowStartPrice: 300,
			lastSnapshotAt: '2026-08-05T08:00:00Z'
		});
		const body = renderComponent(LatestListingTable, { rows: [row] });
		expect(body).toContain('Stale');
		expect(body).toContain('last seen');
	});

	it('hides the model and category columns in compact mode', () => {
		const body = renderComponent(LatestListingTable, { rows: [latestListing()], compact: true });
		expect(body).not.toContain('>Model</th>');
		expect(body).not.toContain('>Category</th>');
		expect(body).toContain('>Retailer</th>');
		expect(body).toContain('scorptec');
	});
});

function productGroup(overrides: Partial<ProductGroup> = {}): ProductGroup {
	return {
		productId: 1,
		category: 'cpu',
		brand: 'AMD',
		model: 'Ryzen 5 7600',
		productVariant: null,
		generationTier: 'current',
		listings: [latestListing()],
		cheapestInStockPrice: 299,
		cheapestInStockRetailer: 'scorptec',
		inStockCount: 1,
		...overrides
	};
}

describe('ProductCard', () => {
	it('renders model, brand, category and the cheapest in-stock price', () => {
		const body = renderComponent(ProductCard, { group: productGroup() });
		expect(body).toContain('Ryzen 5 7600');
		expect(body).toContain('AMD');
		expect(body).toContain('fill="#ED1C24"');
		expect(body).toContain('CPU');
		expect(body).toContain('from $299');
		expect(body).toContain('scorptec');
		// The card content grows to fill the grid cell and the price row keeps a
		// consistent height whether or not a sparkline is present.
		expect(body).toContain('class="grow p-3"');
		expect(body).toContain('mt-2 flex min-h-7 items-center gap-2');
	});

	it('shows a no-in-stock note when nothing is in stock', () => {
		const body = renderComponent(ProductCard, {
			group: productGroup({
				cheapestInStockPrice: null,
				cheapestInStockRetailer: null,
				inStockCount: 0
			})
		});
		expect(body).toContain('No in-stock listings');
	});

	it('keeps the variant listings collapsed by default', () => {
		const body = renderComponent(ProductCard, { group: productGroup() });
		expect(body).not.toContain('<table');
		expect(body).toContain('Show 1 listing');
	});

	it('lists the total and in-stock listing counts', () => {
		const body = renderComponent(ProductCard, {
			group: productGroup({
				listings: [latestListing(), latestListing({ listingId: 2, retailer: 'pccg' })],
				cheapestInStockPrice: 289,
				cheapestInStockRetailer: 'pccg',
				inStockCount: 2
			})
		});
		expect(body).toContain('2 listings');
		expect(body).toContain('2 in stock');
	});

	it('omits the compare checkbox when no toggle handler is provided', () => {
		const body = renderComponent(ProductCard, { group: productGroup() });
		expect(body).not.toContain('Add to compare');
	});

	it('renders the compare checkbox with checked and disabled states', () => {
		const target = document.createElement('div');
		const comp = mount(ProductCard, {
			target,
			props: {
				group: productGroup(),
				compareSelected: true,
				compareDisabled: true,
				onToggleCompare: () => {}
			}
		});
		expect(target.innerHTML).toContain('Add Ryzen 5 7600 to compare');
		const input = target.querySelector('input[type="checkbox"]') as HTMLInputElement;
		expect(input.checked).toBe(true);
		expect(input.disabled).toBe(true);
		unmount(comp);
	});

	it('fires onToggleCompare with the product id when toggled', () => {
		const target = document.createElement('div');
		const onToggleCompare = vi.fn();
		const comp = mount(ProductCard, {
			target,
			props: { group: productGroup(), onToggleCompare }
		});
		const input = target.querySelector('input[type="checkbox"]') as HTMLInputElement;
		input.checked = true;
		input.dispatchEvent(new Event('change', { bubbles: true }));
		expect(onToggleCompare).toHaveBeenCalledWith(1);
		unmount(comp);
	});

	it('renders a trend sparkline on the unexpanded card when history exists', () => {
		const body = renderComponent(ProductCard, {
			group: productGroup({
				sparkline: [
					{ date: '2026-08-16', price: 299 },
					{ date: '2026-08-17', price: 289 },
					{ date: '2026-08-18', price: 285 }
				]
			})
		});
		expect(body).toContain('<polyline');
	});

	it('still shows the sparkline on a no-in-stock card with history', () => {
		const body = renderComponent(ProductCard, {
			group: productGroup({
				cheapestInStockPrice: null,
				cheapestInStockRetailer: null,
				inStockCount: 0,
				sparkline: [
					{ date: '2026-08-16', price: 299 },
					{ date: '2026-08-17', price: 289 },
					{ date: '2026-08-18', price: 285 }
				]
			})
		});
		expect(body).toContain('No in-stock listings');
		expect(body).toContain('<polyline');
	});

	it('omits the card sparkline when there is no in-stock history', () => {
		const body = renderComponent(ProductCard, {
			group: productGroup({ sparkline: [] })
		});
		expect(body).not.toContain('<polyline');
	});
});

function specRow(overrides: Partial<SpecRow> = {}): SpecRow {
	return {
		spec_id: 1,
		product_id: 1,
		source: 'rightnow-gpu-db',
		source_record_key: 'GeForce RTX 5060 Ti',
		category: 'gpu',
		architecture: 'Blackwell',
		generation: 'RTX 50',
		launch_date: '2025-04-16',
		launch_msrp_usd: null,
		vram_gb: 16,
		memory_bus_width_bit: 128,
		memory_type: 'GDDR7',
		tdp_watts: 180,
		core_count: 4608,
		thread_count: null,
		base_clock_mhz: null,
		boost_clock_mhz: null,
		socket: null,
		cache_l3_mb: null,
		gpu_die: null,
		bus_interface: null,
		memory_bandwidth_gbps: null,
		memory_clock_mhz: null,
		process_nm: null,
		foundry: null,
		codename: null,
		l1_cache_kb: null,
		l2_cache_mb: null,
		memory_speed_mhz: null,
		memory_channels: null,
		memory_types: null,
		integrated_graphics: null,
		raw_json: '{}',
		last_synced_at: '2026-08-15T00:00:00Z',
		...overrides
	};
}

describe('SpecPanel', () => {
	it('renders the gpu decision fields', () => {
		const body = renderComponent(SpecPanel, { spec: specRow() });
		expect(body).toContain('RTX 50 — Blackwell');
		expect(body).toContain('16GB GDDR7');
		expect(body).toContain('4,608');
		expect(body).toContain('180 W');
	});

	it('renders the cpu decision fields', () => {
		const body = renderComponent(SpecPanel, {
			spec: specRow({
				category: 'cpu',
				architecture: 'Zen 5',
				generation: 'Ryzen 9000',
				vram_gb: null,
				memory_bus_width_bit: null,
				memory_type: null,
				tdp_watts: 170,
				core_count: 16,
				thread_count: 32,
				base_clock_mhz: 4300,
				boost_clock_mhz: 5700,
				socket: 'AM5'
			})
		});
		expect(body).toContain('Ryzen 9000 — Zen 5');
		expect(body).toContain('16 cores / 32 threads');
		expect(body).toContain('4.3 / 5.7 GHz');
		expect(body).toContain('170 W');
	});

	it('omits rows for null fields', () => {
		const body = renderComponent(SpecPanel, {
			spec: specRow({
				architecture: null,
				generation: null,
				vram_gb: null,
				memory_type: null,
				memory_bus_width_bit: null,
				core_count: null,
				thread_count: null,
				base_clock_mhz: null,
				boost_clock_mhz: null,
				tdp_watts: null,
				launch_date: null
			})
		});
		expect(body).not.toContain('Generation');
		expect(body).not.toContain('VRAM');
		expect(body).not.toContain('TDP');
		expect(body).toContain('Show full specs');
	});

	it('keeps the full specs section collapsed by default', () => {
		const body = renderComponent(SpecPanel, { spec: specRow() });
		expect(body).toContain('<details');
		expect(body).not.toContain('<details open');
	});

	it('shows the launch MSRP when present', () => {
		const body = renderComponent(SpecPanel, { spec: specRow({ launch_msrp_usd: 1999 }) });
		expect(body).toContain('Launch MSRP');
		expect(body).toContain('$1,999');
	});

	it('shows GPU detail rows (die, bandwidth, process)', () => {
		const body = renderComponent(SpecPanel, {
			spec: specRow({
				gpu_die: 'GB202',
				bus_interface: 'PCIe 5.0 x16',
				memory_bandwidth_gbps: 1790,
				memory_clock_mhz: 1750,
				process_nm: 5,
				foundry: 'TSMC',
				l2_cache_mb: 96
			})
		});
		expect(body).toContain('GB202');
		expect(body).toContain('PCIe 5.0 x16');
		expect(body).toContain('1.79 TB/s');
		expect(body).toContain('1750 MHz');
		expect(body).toContain('TSMC 5 nm');
		expect(body).toContain('96 MB');
	});

	it('shows CPU detail rows (codename, memory, caches)', () => {
		const body = renderComponent(SpecPanel, {
			spec: specRow({
				category: 'cpu',
				architecture: 'Zen 5',
				generation: 'Ryzen 9000',
				vram_gb: null,
				memory_bus_width_bit: null,
				memory_type: null,
				tdp_watts: 170,
				core_count: 16,
				thread_count: 32,
				base_clock_mhz: 4300,
				boost_clock_mhz: 5700,
				socket: 'AM5',
				cache_l3_mb: 64,
				codename: 'Granite Ridge',
				l1_cache_kb: 1280,
				l2_cache_mb: 16,
				memory_speed_mhz: 5600,
				memory_channels: 2,
				memory_types: 'DDR5',
				integrated_graphics: 'AMD Radeon Graphics',
				process_nm: null,
				foundry: null
			})
		});
		expect(body).toContain('Granite Ridge');
		expect(body).toContain('DDR5');
		expect(body).toContain('5600 MHz');
		expect(body).toContain('1280 KB');
		expect(body).toContain('16 MB');
		expect(body).toContain('AMD Radeon Graphics');
	});
});

describe('CommandPalette', () => {
	it('shows a bordered empty-state panel when nothing matches', async () => {
		const target = document.createElement('div');
		const comp = mount(CommandPalette, {
			target,
			props: {
				items: [
					{
						id: 1,
						category: 'cpu' as const,
						brand: 'AMD',
						model: 'Ryzen 5 7600',
						productVariant: null,
						snapshotCount: 7
					}
				],
				open: true,
				onToggle: () => {},
				onClose: () => {}
			}
		});
		await tick();
		const input = target.querySelector('input[aria-label="Search products"]') as HTMLInputElement;
		input.value = 'zzz-no-match';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		expect(target.innerHTML).toContain('No matches.');
		expect(target.innerHTML).toContain('rounded-md border border-border bg-surface');
		unmount(comp);
	});
});

function snapshot(date: string, price: number, stock: string): SnapshotRow {
	return {
		id: 1,
		retailer_listing_id: 1,
		snapshot_date: date,
		price_aud: price,
		stock_status: stock as SnapshotRow['stock_status'],
		scraped_at: `${date}T04:00:00.000Z`
	};
}

function listingSeries(id: number, variant: string, points: SnapshotRow[]): Series {
	const listing: ListingRow = {
		id,
		product_id: 1,
		retailer: 'scorptec',
		variant_name: variant,
		retailer_sku: null,
		listing_url: `https://example.com/${id}`,
		status: 'active',
		first_seen_at: '2026-08-09T04:00:00.000Z',
		last_seen_at: '2026-08-17T04:00:00.000Z',
		last_snapshot_at: '2026-08-17T04:00:00.000Z'
	};
	return { listing, points };
}

const BGL_SERIES = [
	listingSeries(1, 'MSI GeForce RTX 5060 Ventus 2X OC 8GB', [
		snapshot('2026-08-17', 619, 'in_stock')
	]),
	listingSeries(2, 'MSI GeForce RTX 5060 Shadow 2X OC 8GB', [
		snapshot('2026-08-17', 635, 'out_of_stock')
	]),
	listingSeries(3, 'Gigabyte GeForce RTX 5060 Windforce OC 8GB', [
		snapshot('2026-08-17', 649, 'in_stock')
	])
];

describe('BrandGroupedListings', () => {
	it('renders group headers with price ranges and in-stock counts', () => {
		const body = renderComponent(BrandGroupedListings, {
			series: BGL_SERIES,
			productBrand: 'NVIDIA',
			selected: new Set<number>(),
			onToggleListing: () => {}
		});
		expect(body).toContain('Retailer listings');
		expect(body).toContain('MSI · $619–$635 · 2 listings · 1 in stock');
		expect(body).toContain('Gigabyte · $649 · 1 listing · 1 in stock');
	});

	it('shows the expand/collapse-all control when more than one group exists', () => {
		const body = renderComponent(BrandGroupedListings, {
			series: BGL_SERIES,
			productBrand: 'NVIDIA',
			selected: new Set<number>(),
			onToggleListing: () => {}
		});
		expect(body).toContain('Expand all');
	});

	it('keeps listing rows collapsed by default', () => {
		const body = renderComponent(BrandGroupedListings, {
			series: BGL_SERIES,
			productBrand: 'NVIDIA',
			selected: new Set<number>(),
			onToggleListing: () => {}
		});
		expect(body).not.toContain('Ventus');
		expect(body).not.toContain('Show on chart');
	});

	it('expands a group on header click and renders listing rows', async () => {
		const target = document.createElement('div');
		const comp = mount(BrandGroupedListings, {
			target,
			props: { series: BGL_SERIES, productBrand: 'NVIDIA', selected: new Set<number>(), onToggleListing: () => {} }
		});
		(target.querySelector('button[aria-expanded]') as HTMLElement).click();
		await tick();
		expect(target.innerHTML).toContain('Ventus');
		expect(target.innerHTML).toContain('Show on chart');
		unmount(comp);
	});

	it('filters groups via the search input', async () => {
		const target = document.createElement('div');
		const comp = mount(BrandGroupedListings, {
			target,
			props: { series: BGL_SERIES, productBrand: 'NVIDIA', selected: new Set<number>(), onToggleListing: () => {} }
		});
		const input = target.querySelector('input[aria-label="Filter listings by name"]') as HTMLInputElement;
		input.value = 'windforce';
		input.dispatchEvent(new Event('input'));
		await tick();
		expect(target.innerHTML).toContain('Gigabyte · $649 · 1 listing · 1 in stock');
		expect(target.innerHTML).not.toContain('MSI');
		unmount(comp);
	});

	it('shows the empty state when no listings match', async () => {
		const target = document.createElement('div');
		const comp = mount(BrandGroupedListings, {
			target,
			props: { series: BGL_SERIES, productBrand: 'NVIDIA', selected: new Set<number>(), onToggleListing: () => {} }
		});
		const input = target.querySelector('input[aria-label="Filter listings by name"]') as HTMLInputElement;
		input.value = 'does-not-exist';
		input.dispatchEvent(new Event('input'));
		await tick();
		expect(target.innerHTML).toContain('No listings match the current filters.');
		// Matches the standard empty-state panel treatment used elsewhere
		expect(target.innerHTML).toContain('rounded-md border border-border bg-surface px-4 py-8');
		unmount(comp);
	});

	it('calls onToggleListing with the listing id when toggling onto the chart', async () => {
		const target = document.createElement('div');
		const onToggleListing = vi.fn();
		const comp = mount(BrandGroupedListings, {
			target,
			props: {
				series: BGL_SERIES,
				productBrand: 'NVIDIA',
				selected: new Set<number>(),
				onToggleListing
			}
		});
		(target.querySelector('button[aria-expanded]') as HTMLElement).click();
		await tick();
		(target.querySelectorAll('button[aria-pressed]')[0] as HTMLButtonElement).click();
		expect(onToggleListing).toHaveBeenCalledWith(1);
		unmount(comp);
	});
});

function cheapestListing(overrides: Partial<CheapestListing> = {}): CheapestListing {
	return {
		productId: 1,
		model: 'RTX 5060 Ti',
		brand: 'NVIDIA',
		variantName: 'Gigabyte GeForce RTX 5060 Ti Windforce OC 16GB',
		retailer: 'scorptec',
		price: 849,
		snapshotDate: '2026-08-17',
		ninetyDayLow: 799,
		ninetyDayHigh: 899,
		...overrides
	};
}

describe('CheapestCarousel', () => {
	it('shows the 90d low badge when the price matches the 90-day low', () => {
		const listing = cheapestListing({ price: 799 });
		const body = renderComponent(CheapestCarousel, { gpu: [listing], cpu: [] });
		expect(body).toContain('90d low');
		expect(body).toContain('$799');
	});

	it('omits the 90d low badge when the price is above the 90-day low', () => {
		const body = renderComponent(CheapestCarousel, { gpu: [cheapestListing()], cpu: [] });
		expect(body).not.toContain('90d low');
		expect(body).toContain('$849');
	});

	it('shows a tooltip title with the full variant name on the card', () => {
		const body = renderComponent(CheapestCarousel, { gpu: [cheapestListing()], cpu: [] });
		expect(body).toContain('title="Gigabyte GeForce RTX 5060 Ti Windforce OC 16GB"');
	});
});

function sparkline(prices: number[]): SparklinePoint[] {
	return prices.map((price, i) => ({
		listingId: 1,
		date: `2026-08-${String(9 + i).padStart(2, '0')}`,
		price
	}));
}

describe('Sparkline', () => {
	it('renders a dash when there are fewer than two points', () => {
		const body = renderComponent(Sparkline, { points: sparkline([299]) });
		expect(body).toContain('—');
		expect(body).not.toContain('<polyline');
	});

	it('renders a dash when points are undefined', () => {
		const body = renderComponent(Sparkline, { points: undefined });
		expect(body).toContain('—');
	});

	it('uses the up (red/coral) stroke when the price increased', () => {
		const body = renderComponent(Sparkline, { points: sparkline([299, 320, 310, 330]) });
		expect(body).toContain('stroke-up');
		expect(body).toContain('<polyline');
	});

	it('uses the down (green/teal) stroke when the price decreased', () => {
		const body = renderComponent(Sparkline, { points: sparkline([330, 310, 300, 290]) });
		expect(body).toContain('stroke-down');
		expect(body).toContain('<polyline');
	});

	it('labels the trend with the start and end prices', () => {
		const body = renderComponent(Sparkline, { points: sparkline([299, 330]) });
		expect(body).toContain('$299 → $330');
	});
});