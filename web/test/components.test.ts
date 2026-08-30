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
import SpecPanel from '../src/lib/components/SpecPanel.svelte';
import Sparkline from '../src/lib/components/Sparkline.svelte';
import OfferRow from '../src/lib/components/OfferRow.svelte';
import FacetChips from '../src/lib/components/FacetChips.svelte';
import OfferList from '../src/lib/components/OfferList.svelte';
import ProductRow from '../src/lib/components/ProductRow.svelte';
import HealthStrip from '../src/lib/components/HealthStrip.svelte';
import MoverRow from '../src/lib/components/MoverRow.svelte';
import CategorySection from '../src/lib/components/CategorySection.svelte';
import { offer as offerRow } from './helpers/offers';
import type { LatestListing, ProductGroup, Series, CheapestListing, SparklinePoint, Mover } from '../src/lib/server/repos';
import type { ListingRow, SpecRow, SnapshotRow } from '../src/lib/server/db';
import type { Retailer } from '../src/lib/types';

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
		avg30: null,
		avg30Points: 0,
		...overrides
	};
}

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

describe('OfferRow', () => {
	it('shows the price, brand and retailer on every row', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(html).toContain('$1,299');
		expect(html).toContain('ASUS');
		expect(html).toContain('Scorptec');
	});

	it('links out to the retailer with a safe target', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(html).toContain('href="https://example.com/1"');
		expect(html).toContain('rel="noopener noreferrer"');
	});

	it('shows a down-arrow delta with a signed number when below the average', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow({ latestPrice: 1288 }),
			avg30: 1400,
			avgPoints: 17
		});
		expect(html).toContain('▼');
		// States the days that actually back the average rather than claiming 30.
		expect(html).toContain('vs 17-day avg');
		expect(html).not.toContain('30d avg');
	});

	it('falls back to a day-count-free label when the point count is unknown', () => {
		const html = renderComponent(OfferRow, { offer: offerRow({ latestPrice: 1288 }), avg30: 1400 });
		expect(html).toContain('vs recent avg');
	});

	it('shows an up arrow when above the average', () => {
		const html = renderComponent(OfferRow, { offer: offerRow({ latestPrice: 1500 }), avg30: 1400 });
		expect(html).toContain('▲');
	});

	it('renders a flat price as neutral, never a rise — no arrow, no directional colour', () => {
		const html = renderComponent(OfferRow, { offer: offerRow({ latestPrice: 189 }), avg30: 189 });
		expect(html).not.toContain('▲');
		expect(html).not.toContain('▼');
		expect(html).not.toContain('text-up');
		expect(html).not.toContain('text-down');
		expect(html).toContain('·');
		expect(html).toContain('vs recent avg');
	});

	it('says so plainly when there is not enough history, rather than showing a number', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: null });
		expect(html).toContain('Not enough history');
		expect(html).not.toContain('-day avg');
	});

	it('marks a delisted offer and omits its stock badge', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow({ delisted: true, inStock: false }),
			avg30: 1400
		});
		expect(html).toContain('Delisted');
	});

	it('renders no price for an offer that has never had one', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow({ latestPrice: null, inStock: false, latestStock: 'unknown' }),
			avg30: 1400
		});
		expect(html).toContain('—');
	});

	// /deals reuses this row at product level: the title becomes the model name
	// and links to the product page, while the retailer link stays outbound.
	it('uses the variant name as the title by default', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(html).toContain('ASUS TUF RTX 5070 Ti OC 16GB');
	});

	it('renders titleOverride instead of the variant name', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			titleOverride: 'GeForce RTX 5070 Ti'
		});
		expect(html).toContain('GeForce RTX 5070 Ti');
		expect(html).not.toContain('ASUS TUF RTX 5070 Ti OC 16GB');
	});

	it('links the title to detailHref when given', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			titleOverride: 'GeForce RTX 5070 Ti',
			detailHref: '/product/5'
		});
		expect(html).toContain('href="/product/5"');
	});

	it('keeps the outbound retailer link separate from the detail link', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			titleOverride: 'GeForce RTX 5070 Ti',
			detailHref: '/product/5'
		});
		expect(html).toContain('href="https://example.com/1"');
		expect(html).toContain('href="/product/5"');
	});

	it('renders a plain title, not a link, when no detailHref is given', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			titleOverride: 'GeForce RTX 5070 Ti'
		});
		expect(html).not.toContain('href="/product/');
	});
});

describe('FacetChips', () => {
	const twoOptions = [
		{ value: 'scorptec', label: 'Scorptec', count: 4 },
		{ value: 'pccg', label: 'PCCG', count: 3 }
	];

	it('renders a chip per option with its count, plus an All chip', () => {
		const html = renderComponent(FacetChips, {
			label: 'Retailer',
			options: twoOptions,
			selected: null,
			allCount: 7,
			onSelect: () => {}
		});
		expect(html).toContain('Scorptec');
		expect(html).toContain('4');
		expect(html).toContain('All');
	});

	it('renders nothing when there is only one value to choose from', () => {
		const html = renderComponent(FacetChips, {
			label: 'Brand',
			options: [{ value: 'ASUS', label: 'ASUS', count: 5 }],
			selected: null,
			allCount: 5,
			onSelect: () => {}
		});
		expect(html.replace(/<!--.*?-->/g, '').trim()).toBe('');
	});

	it('renders nothing for no options', () => {
		const html = renderComponent(FacetChips, {
			label: 'Brand',
			options: [],
			selected: null,
			allCount: 0,
			onSelect: () => {}
		});
		expect(html.replace(/<!--.*?-->/g, '').trim()).toBe('');
	});

	it('marks the selected chip with aria-pressed for assistive tech', () => {
		const html = renderComponent(FacetChips, {
			label: 'Retailer',
			options: twoOptions,
			selected: 'pccg',
			allCount: 7,
			onSelect: () => {}
		});
		expect(html).toContain('aria-pressed="true"');
	});
});

function snap(date: string, price: number, stock: string): SnapshotRow {
	return {
		id: 1,
		retailer_listing_id: 1,
		snapshot_date: date,
		price_aud: price,
		stock_status: stock as SnapshotRow['stock_status'],
		scraped_at: `${date}T04:00:00.000Z`
	};
}

function ser(
	id: number,
	variant: string,
	price: number,
	stock = 'in_stock',
	retailer: Retailer = 'scorptec'
): Series {
	const listing: ListingRow = {
		id,
		product_id: 1,
		retailer,
		variant_name: variant,
		retailer_sku: `SKU${id}`,
		listing_url: `https://example.com/${id}`,
		status: 'active',
		first_seen_at: '2026-03-12T04:00:00.000Z',
		last_seen_at: '2026-08-23T04:00:00.000Z',
		last_snapshot_at: '2026-08-23T04:00:00.000Z'
	};
	return { listing, points: [snap('2026-08-23', price, stock)] };
}

describe('OfferList', () => {
	const base = {
		productBrand: 'NVIDIA',
		avg30: 1400,
		selected: new Set<number>(),
		onToggleListing: () => {}
	};

	it('shows at most 8 offers and an expander stating the true total', () => {
		const series = Array.from({ length: 12 }, (_, i) =>
			ser(i + 1, `ASUS Card ${i + 1}`, 1000 + i)
		);
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).toContain('Show all 12 offers');
	});

	it('renders no expander when there are 8 or fewer offers', () => {
		const series = Array.from({ length: 8 }, (_, i) => ser(i + 1, `ASUS Card ${i + 1}`, 1000 + i));
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).not.toContain('Show all');
	});

	it('defaults to in-stock only and says what it is hiding', () => {
		const series = [
			ser(1, 'ASUS In Stock', 1299, 'in_stock'),
			ser(2, 'ASUS Sold Out', 999, 'out_of_stock')
		];
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).toContain('1 of 2');
		expect(html).toContain('ASUS In Stock');
		expect(html).not.toContain('ASUS Sold Out');
	});

	it('shows everything when nothing is in stock, rather than an empty list', () => {
		const series = [
			ser(1, 'ASUS Sold Out', 1299, 'out_of_stock'),
			ser(2, 'MSI Sold Out', 1199, 'out_of_stock')
		];
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).toContain('ASUS Sold Out');
		expect(html).toContain('MSI Sold Out');
	});

	it('puts the cheapest in-stock offer first', () => {
		const series = [ser(1, 'ASUS Pricey', 1499), ser(2, 'MSI Cheap', 1099)];
		const html = renderComponent(OfferList, { ...base, series });
		expect(html.indexOf('MSI Cheap')).toBeLessThan(html.indexOf('ASUS Pricey'));
	});

	it('renders an empty state when there are no listings at all', () => {
		const html = renderComponent(OfferList, { ...base, series: [] });
		expect(html).toContain('No listings');
	});

	it('computes facet counts and the "All" count over the stock-filtered set, not the raw list', () => {
		const series = [
			ser(1, 'ASUS PCCG A', 700, 'in_stock', 'pccg'),
			ser(2, 'ASUS PCCG B', 710, 'in_stock', 'pccg'),
			ser(3, 'MSI SCT A', 690, 'in_stock', 'scorptec'),
			ser(4, 'MSI SCT B', 695, 'out_of_stock', 'scorptec'),
			ser(5, 'MSI SCT C', 699, 'out_of_stock', 'scorptec')
		];
		const html = renderComponent(OfferList, { ...base, series });
		// 3 in stock (2 pccg + 1 scorptec); the two out-of-stock rows are
		// hidden by the default filter and must not inflate the counts, or a
		// chip's count promises rows a click on it cannot produce.
		expect(html).toMatch(/All\s*<span class="num">3<\/span>/);
		expect(html).toMatch(/PCCG\s*<span class="num">2<\/span>/);
		expect(html).toMatch(/Scorptec\s*<span class="num">1<\/span>/);
	});

	it('never offers a facet chip for a retailer with zero in-stock offers — clicking it would dead-end into an empty list', () => {
		const series = [
			ser(1, 'ASUS PCCG A', 700, 'in_stock', 'pccg'),
			ser(2, 'ASUS PCCG B', 710, 'in_stock', 'pccg'),
			ser(3, 'ASUS PCCG C', 720, 'in_stock', 'pccg'),
			ser(4, 'MSI SCT A', 690, 'out_of_stock', 'scorptec'),
			ser(5, 'MSI SCT B', 695, 'out_of_stock', 'scorptec')
		];
		const html = renderComponent(OfferList, { ...base, series });
		// All PCCG offers are in stock and all Scorptec offers are not — with
		// the default in-stock-only filter there is only one retailer left to
		// choose from, so the whole facet row hides itself rather than
		// offering a "Scorptec" chip that renders no rows when clicked.
		expect(html).not.toContain('Scorptec');
	});

	it('resets a selected chip when its facet option disappears, rather than leaving the list filtered by an invisible control', async () => {
		const series = [
			ser(1, 'ASUS PCCG A', 700, 'in_stock', 'pccg'),
			ser(2, 'ASUS PCCG B', 710, 'in_stock', 'pccg'),
			ser(3, 'ASUS PCCG C', 720, 'in_stock', 'pccg'),
			ser(4, 'MSI SCT A', 690, 'out_of_stock', 'scorptec'),
			ser(5, 'MSI SCT B', 695, 'out_of_stock', 'scorptec'),
			ser(6, 'MSI SCT C', 699, 'out_of_stock', 'scorptec')
		];
		const target = document.createElement('div');
		const comp = mount(OfferList, { target, props: { ...base, series } });

		// Turn the stock filter off so both retailer chips are visible.
		const checkbox = target.querySelector('input[type="checkbox"]') as HTMLInputElement;
		checkbox.checked = false;
		checkbox.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();

		const scorptecChip = Array.from(target.querySelectorAll('button')).find((b) =>
			b.textContent?.trim().startsWith('Scorptec')
		) as HTMLButtonElement;
		expect(scorptecChip).toBeTruthy();
		scorptecChip.click();
		await tick();
		expect(scorptecChip.getAttribute('aria-pressed')).toBe('true');

		// Turn the stock filter back on: every Scorptec offer is out of stock,
		// so the Scorptec chip — and the whole facet row — disappears. The
		// reset effect fires off the back of that render, so give it a second
		// tick to settle.
		checkbox.checked = true;
		checkbox.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		await tick();

		expect(target.innerHTML).not.toContain('No listings match the current filters');
		expect(target.innerHTML).toContain('ASUS PCCG A');

		unmount(comp);
	});

	it('announces the visible offer count via aria-live when filters change', () => {
		const series = [ser(1, 'ASUS A', 700, 'in_stock'), ser(2, 'ASUS B', 710, 'in_stock')];
		const html = renderComponent(OfferList, { ...base, series });
		expect(html).toMatch(/aria-live="polite"[^>]*>\s*2\s*offers match the current filters\./);
	});
});

import PriceRangeBar from '../src/lib/components/PriceRangeBar.svelte';

describe('PriceRangeBar', () => {
	it('describes itself in words for assistive tech', () => {
		const html = renderComponent(PriceRangeBar, {
			low: 1249,
			high: 1689,
			current: 1469,
			position: 0.5
		});
		expect(html).toContain('role="img"');
		// Verify aria-label specifically contains all three prices in the correct order
		// (current, then low, then high) as specified in the component
		expect(html).toMatch(/aria-label="[^"]*\$1,469[^"]*\$1,249[^"]*\$1,689[^"]*"/);
	});

	it('places the marker at the given position', () => {
		const html = renderComponent(PriceRangeBar, {
			low: 1000,
			high: 2000,
			current: 1250,
			position: 0.25
		});
		expect(html).toContain('25%');
	});

	it('degrades to a plain text line when a bar would be meaningless', () => {
		const html = renderComponent(PriceRangeBar, {
			low: 1299,
			high: 1299,
			current: 1299,
			position: null
		});
		expect(html).not.toContain('role="img"');
		expect(html).toContain('$1,299');
	});
});

import ProductHeadline from '../src/lib/components/ProductHeadline.svelte';
import type { Headline } from '../src/lib/productHeadline';

function headline(overrides: Partial<Headline> = {}): Headline {
	return {
		currentPrice: 1299,
		currentRetailer: 'scorptec',
		allTimeLow: 1249,
		allTimeHigh: 1689,
		avg30: 1400,
		avgPoints: 17,
		pricePoints: 17,
		vsAvg30Pct: -7.2,
		vsAllTimeLowPct: 4.0,
		rangePosition: 0.11,
		...overrides
	};
}

describe('ProductHeadline', () => {
	const base = { listingCount: 6, snapshotCount: 47, span: '12 Mar – 23 Aug 2026' };

	it('leads with the current cheapest price and its retailer', () => {
		const html = renderComponent(ProductHeadline, { headline: headline(), ...base });
		expect(html).toContain('$1,299');
		expect(html).toContain('Scorptec');
	});

	it('shows both deltas with arrows, not colour alone', () => {
		const html = renderComponent(ProductHeadline, { headline: headline(), ...base });
		expect(html).toContain('▼');
		expect(html).toContain('vs 17-day avg');
		expect(html).toContain('above all-time low');
		// Verify actual percentages match the fixture values (not hardcoded)
		expect(html).toContain('−7.2%');
		expect(html).toContain('+4.0%');
	});

	it('demotes provenance to one muted line', () => {
		const html = renderComponent(ProductHeadline, { headline: headline(), ...base });
		expect(html).toContain('6 listings');
		expect(html).toContain('47 snapshots');
		expect(html).toContain('12 Mar – 23 Aug 2026');
	});

	it('says there is no in-stock price rather than printing a bare dash', () => {
		const html = renderComponent(ProductHeadline, {
			headline: headline({ currentPrice: null, currentRetailer: null, rangePosition: null }),
			...base
		});
		expect(html).toContain('No in-stock listings');
	});

	it('still shows the all-time low and high when nothing is in stock', () => {
		const html = renderComponent(ProductHeadline, {
			headline: headline({ currentPrice: null, currentRetailer: null, rangePosition: null }),
			...base
		});
		expect(html).toContain('No in-stock listings');
		expect(html).toContain('$1,249');
		expect(html).toContain('$1,689');
		// The range bar needs a current position to place its marker, so it
		// must stay hidden — but the two figures must not vanish with it.
		expect(html).not.toContain('role="img"');
	});

	it('says so plainly, rather than going silent, when history is too thin for the 30-day delta', () => {
		const html = renderComponent(ProductHeadline, {
			headline: headline({ avg30: null, vsAvg30Pct: null }),
			...base
		});
		expect(html).not.toContain('30d avg');
		expect(html).toContain('Not enough history');
	});

	it('renders a flat price as neutral, never a rise — no arrow, no directional colour', () => {
		const html = renderComponent(ProductHeadline, {
			// vsAllTimeLowPct nulled out — it renders its own unrelated arrow —
			// so this test isolates the vs-30d-avg delta this fix is about.
			headline: headline({ vsAvg30Pct: 0, vsAllTimeLowPct: null }),
			...base
		});
		expect(html).not.toContain('▲');
		expect(html).not.toContain('▼');
		expect(html).not.toContain('class="text-up"');
		expect(html).not.toContain('class="text-down"');
		expect(html).toContain('0.0%');
		expect(html).toContain('vs 17-day avg');
	});
});
describe('HealthStrip', () => {
	const health = [
		{ retailer: 'scorptec', label: 'Scorptec', state: 'fresh' as const, days: 0, text: 'today' },
		{ retailer: 'pccg', label: 'PCCG', state: 'stale' as const, days: 3, text: '3 days behind' }
	];

	it('states each retailer and its age in words, not colour alone', () => {
		const html = renderComponent(HealthStrip, {
			retailers: health,
			latestSnapshotDate: '2026-08-25',
			snapshotDays: 17,
			snapshotCount: 4988
		});
		expect(html).toContain('Scorptec');
		expect(html).toContain('today');
		expect(html).toContain('PCCG');
		expect(html).toContain('3 days behind');
	});

	it('shows the dataset depth, including the DB size moved out of the header', () => {
		const html = renderComponent(HealthStrip, {
			retailers: health,
			latestSnapshotDate: '2026-08-25',
			snapshotDays: 17,
			snapshotCount: 4988,
			dbSizeBytes: 1153434
		});
		expect(html).toContain('17');
		expect(html).toContain('4,988');
		expect(html).toContain('MB');
	});

	it('omits the DB size when it is unknown', () => {
		const html = renderComponent(HealthStrip, {
			retailers: health,
			latestSnapshotDate: '2026-08-25',
			snapshotDays: 17,
			snapshotCount: 4988,
			dbSizeBytes: 0
		});
		expect(html).toContain('4,988');
		expect(html).not.toContain('MB');
	});

	it('handles an empty database without crashing', () => {
		const html = renderComponent(HealthStrip, {
			retailers: [],
			latestSnapshotDate: null,
			snapshotDays: 0,
			snapshotCount: 0
		});
		expect(html).toContain('No snapshots yet');
	});
});

describe('MoverRow', () => {
	function mover(over: Partial<Mover> = {}): Mover {
		return {
			listingId: 1,
			productId: 5,
			category: 'gpu',
			brand: 'NVIDIA',
			model: 'GeForce RTX 5070 Ti',
			retailer: 'scorptec',
			variantName: 'ASUS TUF RTX 5070 Ti OC 16GB',
			listingUrl: 'https://example.com/1',
			oldPrice: 1400,
			newPrice: 1299,
			change: -101,
			pctChange: -7.2,
			pointsInWindow: 7,
			historyPoints: 30,
			notEnoughHistory: false,
			windowStart: '2026-08-18',
			windowEnd: '2026-08-25',
			...over
		};
	}

	it('shows a down arrow and a signed percentage for a drop', () => {
		const html = renderComponent(MoverRow, { mover: mover() });
		expect(html).toContain('▼');
		expect(html).toContain('7.2%');
		expect(html).toContain('$1,299');
		expect(html).toContain('GeForce RTX 5070 Ti');
	});

	it('shows an up arrow for a rise', () => {
		const html = renderComponent(MoverRow, {
			mover: mover({ pctChange: 5.4, change: 70, oldPrice: 1229, newPrice: 1299 })
		});
		expect(html).toContain('▲');
		expect(html).toContain('5.4%');
	});

	it('links to the product page', () => {
		const html = renderComponent(MoverRow, { mover: mover() });
		expect(html).toContain('href="/product/5"');
	});

	it('shows the retailer and which variant moved', () => {
		const html = renderComponent(MoverRow, { mover: mover() });
		expect(html).toContain('Scorptec · ASUS TUF RTX 5070 Ti OC 16GB');
	});

	it('trims the variant at the first comma, as the movers table does', () => {
		const html = renderComponent(MoverRow, {
			mover: mover({ variantName: 'palit geforce rtx 5070 infinity 3, 12gb' })
		});
		expect(html).toContain('Palit Geforce RTX 5070 Infinity 3');
		expect(html).not.toContain('12gb');
	});

	it('falls back to the retailer alone when the variant is missing', () => {
		const html = renderComponent(MoverRow, { mover: mover({ variantName: null }) });
		expect(html).toContain('Scorptec');
		expect(html).not.toContain('·');
	});

	it('renders a mover with no percentage without crashing', () => {
		const html = renderComponent(MoverRow, {
			mover: mover({ pctChange: null, change: null, oldPrice: null })
		});
		expect(html).toContain('GeForce RTX 5070 Ti');
	});
});

describe('CategorySection', () => {
	const base = {
		title: 'GPUs',
		href: '/products?category=gpu',
		trackedCount: 47,
		cheapestPrice: 329,
		deals: [],
		drops: [],
		rises: []
	};

	it('shows the tracked count and cheapest price in the header', () => {
		const html = renderComponent(CategorySection, base);
		expect(html).toContain('GPUs');
		expect(html).toContain('47');
		expect(html).toContain('$329');
		expect(html).toContain('href="/products?category=gpu"');
	});

	it('gives every empty column real copy, not a blank panel', () => {
		const html = renderComponent(CategorySection, base);
		expect(html).toContain('Nothing below its recent average today.');
		expect(html).toContain('No significant price moves in the last 7 days.');
	});

	it('omits the cheapest figure when there is no in-stock price', () => {
		const html = renderComponent(CategorySection, { ...base, cheapestPrice: null });
		expect(html).not.toContain('cheapest');
	});
});

describe('ProductHeadline honesty', () => {
	it('labels the average with the days that actually back it, not a flat 30', () => {
		const html = renderComponent(ProductHeadline, {
			headline: headline({ avgPoints: 17 }),
			listingCount: 3,
			snapshotCount: 51,
			span: '9 Aug - 25 Aug 2026'
		});
		expect(html).toContain('vs 17-day avg');
		expect(html).not.toContain('30d avg');
	});

	it('says the price has held steady rather than claiming a single reading', () => {
		const html = renderComponent(ProductHeadline, {
			headline: headline({
				allTimeLow: 1299,
				allTimeHigh: 1299,
				rangePosition: null,
				pricePoints: 17
			}),
			listingCount: 3,
			snapshotCount: 51,
			span: '9 Aug - 25 Aug 2026'
		});
		expect(html).toContain('held at');
		expect(html).toContain('17');
		expect(html).not.toContain('Only one price recorded');
	});

	it('still says "only one price" when there genuinely is only one', () => {
		const html = renderComponent(ProductHeadline, {
			headline: headline({
				allTimeLow: 1299,
				allTimeHigh: 1299,
				rangePosition: null,
				pricePoints: 1
			}),
			listingCount: 1,
			snapshotCount: 1,
			span: '25 Aug 2026'
		});
		expect(html).toContain('Only one price recorded');
	});
});

describe('ProductRow', () => {
	const base = {
		productId: 7,
		category: 'gpu',
		brand: 'NVIDIA',
		model: 'GeForce RTX 5070 Ti',
		productVariant: null,
		generationTier: 'current',
		listings: [],
		cheapestInStockPrice: 1599,
		cheapestInStockRetailer: 'pccg',
		inStockCount: 3,
		avg30: 1650,
		avg30Points: 17
	} as unknown as ProductGroup;

	it('shows model, price, retailer and links to the product', () => {
		const html = renderComponent(ProductRow, { group: base });
		expect(html).toContain('GeForce RTX 5070 Ti');
		expect(html).toContain('$1,599');
		expect(html).toContain('PCCG');
		expect(html).toContain('href="/product/7"');
	});

	it('states the average window honestly', () => {
		const html = renderComponent(ProductRow, { group: base });
		expect(html).toContain('17-day avg');
		expect(html).not.toContain('30d avg');
	});

	it('renders a dash and says so when nothing is in stock', () => {
		const html = renderComponent(ProductRow, {
			group: {
				...base,
				cheapestInStockPrice: null,
				cheapestInStockRetailer: null,
				inStockCount: 0
			} as unknown as ProductGroup
		});
		expect(html).toContain('—');
		expect(html).toContain('No stock');
	});

	// A watchlist product no retailer has ever listed is a different claim from
	// one that is listed but out of stock, and the row must not conflate them.
	it('distinguishes never-listed from out-of-stock', () => {
		const neverListed = renderComponent(ProductRow, {
			group: {
				...base,
				cheapestInStockPrice: null,
				cheapestInStockRetailer: null,
				inStockCount: 0,
				avg30: null,
				avg30Points: 0,
				neverListed: true
			} as unknown as ProductGroup
		});
		expect(neverListed).toContain('Not listed');
		expect(neverListed).not.toContain('No stock');

		const outOfStock = renderComponent(ProductRow, {
			group: {
				...base,
				cheapestInStockPrice: null,
				cheapestInStockRetailer: null,
				inStockCount: 0,
				avg30: null,
				avg30Points: 0,
				neverListed: false
			} as unknown as ProductGroup
		});
		expect(outOfStock).toContain('No stock');
		expect(outOfStock).not.toContain('Not listed');
	});

	it('says so when there is too little history to judge', () => {
		const html = renderComponent(ProductRow, {
			group: { ...base, avg30: null, avg30Points: 0 } as unknown as ProductGroup
		});
		expect(html).toContain('Not enough history');
	});

	it('renders a compare checkbox only when a handler is supplied', () => {
		const withBox = renderComponent(ProductRow, { group: base, onToggleCompare: () => {} });
		expect(withBox).toContain('type="checkbox"');
		const without = renderComponent(ProductRow, { group: base });
		expect(without).not.toContain('type="checkbox"');
	});

	// Svelte sets `checked` as a DOM property, not an HTML attribute, so this
	// has to inspect the node rather than the serialised markup.
	function checkboxState(props: Record<string, unknown>): {
		checked: boolean;
		disabled: boolean;
	} {
		const target = document.createElement('div');
		const comp = mount(ProductRow as never, { target, props });
		const input = target.querySelector('input[type="checkbox"]') as HTMLInputElement;
		const state = { checked: input.checked, disabled: input.disabled };
		unmount(comp);
		return state;
	}

	it('reflects compare selection state', () => {
		expect(checkboxState({ group: base, compareSelected: true, onToggleCompare: () => {} }).checked).toBe(true);
		expect(checkboxState({ group: base, compareSelected: false, onToggleCompare: () => {} }).checked).toBe(false);
	});

	it('disables the checkbox when compare is locked to another category', () => {
		expect(
			checkboxState({ group: base, compareDisabled: true, onToggleCompare: () => {} }).disabled
		).toBe(true);
	});
});
