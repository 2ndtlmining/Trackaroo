import { describe, expect, it, vi } from 'vitest';
import { mount, tick, unmount } from 'svelte';
import Badge from '../src/lib/components/Badge.svelte';
import BrandIcon from '../src/lib/components/BrandIcon.svelte';
import CommandPalette from '../src/lib/components/CommandPalette.svelte';
import PriceChange from '../src/lib/components/PriceChange.svelte';
import StockBadge from '../src/lib/components/StockBadge.svelte';
import Chip from '../src/lib/components/Chip.svelte';
import SpecPanel from '../src/lib/components/SpecPanel.svelte';
import Sparkline from '../src/lib/components/Sparkline.svelte';
import OfferRow from '../src/lib/components/OfferRow.svelte';
import FacetChips from '../src/lib/components/FacetChips.svelte';
import OfferList from '../src/lib/components/OfferList.svelte';
import ProductRow from '../src/lib/components/ProductRow.svelte';
import HealthStrip from '../src/lib/components/HealthStrip.svelte';
import MoverRow from '../src/lib/components/MoverRow.svelte';
import CategorySection from '../src/lib/components/CategorySection.svelte';
import BuyPanel from '../src/lib/components/BuyPanel.svelte';
import PriceDataTable from '../src/lib/components/PriceDataTable.svelte';
import SegmentedControl from '../src/lib/components/SegmentedControl.svelte';
import MsrpLine from '../src/lib/components/MsrpLine.svelte';
import SignalBadge from '../src/lib/components/SignalBadge.svelte';
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

	it('renders stale text in the muted text colour, keeping the stale token for the dot (#24)', () => {
		const body = renderComponent(Badge, { label: 'Delisted', tone: 'stale' });
		expect(body).toContain('bg-stale');
		expect(body).toContain('text-text-muted');
		expect(body).not.toContain('text-stale');
	});

	it.each(['success', 'warning', 'danger'])('has a %s status tone', (tone) => {
		const body = renderComponent(Badge, { label: 'x', tone });
		expect(body).toContain(`bg-${tone}`);
		expect(body).toContain(`text-${tone}`);
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
		expect(body).toContain('US launch MSRP');
		expect(body).toContain('US$1,999');
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
						vramGb: null,
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

	// Changed for #6: titleOverride now also shows the listing's variant name
	// as a subtitle (e.g. "Palit Dual 8G"), so a buyer sees which listing they
	// are actually buying, not just the product model.
	it('renders titleOverride as the title, with the variant name as a subtitle (#6)', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			titleOverride: 'GeForce RTX 5070 Ti'
		});
		expect(html).toContain('GeForce RTX 5070 Ti');
		expect(html).toContain('ASUS TUF RTX 5070 Ti OC 16GB');
	});

	it('omits the variant subtitle when there is no titleOverride (#6)', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		// The variant name is still the title itself, just not repeated below it.
		expect(html).not.toContain('text-xs text-text-muted">ASUS TUF RTX 5070 Ti OC 16GB<');
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

	// #6: snapshot dates are compared as whole calendar days, not instants —
	// "updated just now" was misleading for a once-daily scrape.
	it('labels freshness by calendar day, not relative time (#6)', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow({ lastSeen: '2026-08-23' }),
			avg30: 1400
		});
		// 2026-08-23 is always more than a week in the past by the time this
		// test runs, so formatSeenDate always falls through to the short-date
		// form — deterministic regardless of the real clock.
		expect(html).toContain('seen 23 Aug');
		expect(html).not.toContain('updated');
	});

	// #6: below-average rows show the actual dollar saving and the average
	// they are being compared against, not just a bare percentage.
	it('shows the saving in dollars alongside the percentage when saving is given (#6)', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow({ latestPrice: 1288 }),
			avg30: 1400,
			avgPoints: 17,
			saving: 112
		});
		expect(html).toContain('−$112');
		expect(html).toContain('−8.0%');
		expect(html).toContain('vs 17-day avg');
		expect(html).toContain('$1,400');
	});

	it('shows a Lowest since badge when lowSince is given (#6)', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			lowSince: '2026-01-15'
		});
		expect(html).toContain('Lowest since 15 Jan');
	});

	it('omits the Lowest since badge when lowSince is not given (#6)', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(html).not.toContain('Lowest since');
	});

	// M3 (28-Sep finding): earnedLow tolerates a price up to 2% above the
	// all-time low, so a "Lowest since" claim there would overclaim -- the
	// page passes nearLowSince instead of lowSince for that case.
	it('shows a Near low since badge when nearLowSince is given (M3)', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			nearLowSince: '2026-01-15'
		});
		expect(html).toContain('Near low since 15 Jan');
		expect(html).not.toContain('Lowest since');
	});

	it('prefers lowSince over nearLowSince when both are given (M3)', () => {
		const html = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			lowSince: '2026-01-15',
			nearLowSince: '2026-01-10'
		});
		expect(html).toContain('Lowest since 15 Jan');
		expect(html).not.toContain('Near low since');
	});

	it('omits the Near low since badge when nearLowSince is not given (M3)', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(html).not.toContain('Near low since');
	});

	it('labels the outbound link "Buy at <retailer>" with an accessible name (#6)', () => {
		const html = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(html).toMatch(/Buy at Scorptec[^<]*(<!---->)*<svg[^>]*aria-hidden="true"/);
		expect(html).toContain('aria-label="Buy at Scorptec (opens in a new tab)"');
		expect(html).not.toContain('View →');
	});

	it('marks the row with data-testid="deal-row" only when titleOverride is set (#6)', () => {
		const withOverride = renderComponent(OfferRow, {
			offer: offerRow(),
			avg30: 1400,
			titleOverride: 'GeForce RTX 5070 Ti'
		});
		expect(withOverride).toContain('data-testid="deal-row"');

		const without = renderComponent(OfferRow, { offer: offerRow(), avg30: 1400 });
		expect(without).not.toContain('data-testid="deal-row"');
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

	it('fills the segment at the given position', () => {
		const html = renderComponent(PriceRangeBar, {
			low: 1000,
			high: 2000,
			current: 1250,
			position: 0.25
		});
		expect(html).toMatch(/data-segment="1"[^>]*data-filled="true"/);
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

describe('PriceDataTable (#27)', () => {
	const band = [
		{ date: '2026-09-01', low: 700, high: 800, cheapestInStock: null },
		{ date: '2026-09-02', low: null, high: null, cheapestInStock: null },
		{ date: '2026-09-03', low: 690, high: 760, cheapestInStock: 690 }
	];

	it('is a keyboard-reachable disclosure with a real table, newest day first', () => {
		const html = renderComponent(PriceDataTable, { band });
		expect(html).toContain('<details');
		expect(html).toContain('<summary');
		expect(html).toContain('Show price data (3 days)');
		expect(html.indexOf('3 Sep 2026')).toBeLessThan(html.indexOf('1 Sep 2026'));
		expect(html).toContain('$690');
		expect(html).toContain('—');
	});

	it('renders nothing without data', () => {
		expect(renderComponent(PriceDataTable, { band: [] })).not.toContain('<details');
	});
});

describe('PriceRangeBar (U4)', () => {
	it('labels the ends as the lowest and highest day, not cheapest/dearest listings', () => {
		const html = renderComponent(PriceRangeBar, {
			low: 699,
			high: 899,
			current: 749,
			position: 0.25,
			points: 30
		});
		expect(html).toContain('Lowest day');
		expect(html).toContain('Highest day');
		expect(html).not.toMatch(/>\s*(Cheapest|Dearest)\s*</);
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

	it('shows the average delta with an arrow, not colour alone', () => {
		const html = renderComponent(ProductHeadline, { headline: headline(), ...base });
		expect(html).toContain('▼');
		expect(html).toContain('vs 17-day avg');
		expect(html).toContain('−7.2%');
		// "vs the low" moved to BuyPanel, worded "Lowest since", not "all-time" (D5).
		expect(html).not.toContain('all-time low');
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

	it('still shows the recorded low and high when nothing is in stock', () => {
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

describe('BuyPanel (#31)', () => {
	const low = {
		low: 699,
		lowDate: '2026-09-10',
		since: '2026-08-09',
		today: 729,
		pctAbove: 4.29,
		atLow: false
	};
	const windows = [
		{ days: 30, points: 20, low: 699, median: 719, high: 749, enough: true },
		{ days: 90, points: 2, low: 699, median: 714, high: 729, enough: false }
	];
	const where = [
		{ retailer: 'scorptec', cheapest: 719, cheapestUrl: 'https://s/1', inStock: 1, listings: 2 },
		{ retailer: 'umart', cheapest: null, cheapestUrl: null, inStock: 0, listings: 1 }
	];

	it('states the lowest price, its date, the first tracked day and today’s gap', () => {
		const html = renderComponent(BuyPanel, { low, windows, where });
		expect(html).toContain('Lowest since 9 Aug 2026');
		expect(html).toContain('$699');
		expect(html).toContain('10 Sep 2026');
		expect(html).toContain('4.3%');
		expect(html).not.toContain('all-time');
	});

	it('says so when today is the low', () => {
		const html = renderComponent(BuyPanel, {
			low: { ...low, today: 699, pctAbove: 0, atLow: true },
			windows,
			where
		});
		expect(html).toContain('Today is the lowest price since 9 Aug 2026');
	});

	it('shows the strip, and names thin windows instead of guessing (Review Focus 1)', () => {
		const html = renderComponent(BuyPanel, { low, windows, where });
		expect(html).toContain('30 days');
		expect(html).toContain('$719');
		expect(html).toContain('Gathering history (2 days)');
	});

	it('lists each retailer with its cheapest price, stock count and a labelled link', () => {
		const html = renderComponent(BuyPanel, { low, windows, where });
		expect(html).toContain('Scorptec');
		expect(html).toContain('1 of 2');
		expect(html).toContain('Buy at Scorptec for $719 (opens in a new tab)');
		expect(html).toContain('Umart');
		expect(html).toContain('0 of 1');
	});

	it('copes with a product that has never had a price (Review Focus 1)', () => {
		const html = renderComponent(BuyPanel, { low: null, windows: [], where: [] });
		expect(html).toContain('No in-stock price recorded yet');
		expect(html).toContain('No retailer lists it right now');
		expect(html).not.toContain('NaN');
	});

	it('says nothing is in stock today rather than printing a gap', () => {
		const html = renderComponent(BuyPanel, {
			low: { ...low, today: null, pctAbove: null },
			windows,
			where
		});
		expect(html).toContain('Nothing is in stock today');
	});

	it('adds the 180-day column and puts the windows across the top', () => {
		const html = renderComponent(BuyPanel, {
			low,
			windows: [...windows, { days: 180, points: 20, low: 689, median: 719, high: 799, enough: true }],
			where
		});
		expect(html).toMatch(/<th[^>]*scope="col"[^>]*>\s*180 days/);
		expect(html).toMatch(/<th[^>]*scope="row"[^>]*>\s*Median/);
		expect(html).toContain('$689');
	});

	it('renders one badge per signal, claim and evidence both visible', () => {
		const html = renderComponent(BuyPanel, {
			low,
			windows,
			where,
			signals: [
				{ key: 'lowest', tone: 'good', icon: 'check', claim: 'Lowest in 94 days', evidence: 'The price was last lower 94 days ago.' },
				{ key: 'trend', tone: 'warn', icon: 'up', claim: '7-day trend: rising (+3%)', evidence: 'Flat is within 1%.' }
			]
		});
		expect(html.match(/data-testid="signal"/g)).toHaveLength(2);
		expect(html).toContain('Lowest in 94 days');
		expect(html).toContain('The price was last lower 94 days ago.');
		expect(html).toContain('7-day trend: rising (+3%)');
	});
});

describe('SignalBadge (#31)', () => {
	const sig = (tone: string, icon: string) => ({ key: 'avg', tone, icon, claim: 'Claim text', evidence: 'Evidence text' });

	it('shows the claim and the evidence, with a decorative icon', () => {
		const html = renderComponent(SignalBadge, { signal: sig('good', 'check') });
		expect(html).toContain('Claim text');
		expect(html).toContain('Evidence text');
		expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
		expect(html).toContain('lucide-circle-check');
	});

	it.each([
		['good', 'text-success', 'bg-success-soft'],
		['warn', 'text-warning', 'bg-warning-soft'],
		['bad', 'text-danger', 'bg-danger-soft'],
		['neutral', 'text-text-muted', 'bg-surface-hover']
	])('maps tone %s onto existing tokens', (tone, text, bg) => {
		const html = renderComponent(SignalBadge, { signal: sig(tone, 'dash') });
		expect(html).toContain(text);
		expect(html).toContain(bg);
	});

	it.each([
		['check', 'lucide-circle-check'],
		['dash', 'lucide-minus'],
		['down', 'lucide-trending-down'],
		['up', 'lucide-trending-up'],
		['calendar', 'lucide-calendar-clock'],
		['alert', 'lucide-triangle-alert']
	])('icon %s is Lucide %s', (icon, cls) => {
		expect(renderComponent(SignalBadge, { signal: sig('neutral', icon) })).toContain(cls);
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

	it('shows the run detail next to the age when there is one', () => {
		const html = renderComponent(HealthStrip, {
			retailers: [
				{ retailer: 'umart', label: 'Umart', state: 'fresh', days: 0, text: 'today 04:12', detail: '182 matched' },
				{ retailer: 'pccg', label: 'PCCG', state: 'incomplete', days: 1, text: 'timeout at 05:01', detail: null }
			],
			latestSnapshotDate: '2026-08-25',
			snapshotDays: 17,
			snapshotCount: 4988
		});
		expect(html).toContain('today 04:12');
		expect(html).toContain('182 matched');
		expect(html).toContain('timeout at 05:01');
	});

	it('uses status tones, not price-direction colours (#24)', () => {
		const html = renderComponent(HealthStrip, {
			retailers: health,
			latestSnapshotDate: '2026-08-25',
			snapshotDays: 17,
			snapshotCount: 4988
		});
		expect(html).toContain('text-success');
		expect(html).toContain('text-warning');
		expect(html).not.toMatch(/text-(up|down)\b/);
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
		availableCount: 23,
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

	it('says how many of the tracked products can actually be bought', () => {
		// "47 tracked" counted the watchlist and presented it as coverage: on
		// 31-Aug only 23 of those 47 GPUs had a listing at any retailer, the rest
		// being end-of-life parts that have aged out of both catalogues.
		const html = renderComponent(CategorySection, base);
		expect(html).toContain('23');
		expect(html).toContain('47');
		expect(html.replace(/<[^>]*>/g, '')).toMatch(/23\s*of\s*47\s*tracked/);
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

describe('ProductRow catalog columns (#23, U5)', () => {
	const row = {
		productId: 7,
		category: 'gpu' as const,
		brand: 'NVIDIA',
		model: 'GeForce RTX 5070',
		productVariant: null,
		generationTier: 'current' as const,
		cheapestInStockPrice: 899,
		cheapestInStockRetailer: 'scorptec' as const,
		inStockCount: 3,
		avg30: 920,
		avg30Points: 20,
		neverListed: false,
		vramGb: 12,
		cores: null,
		launchDate: '2025-03-05',
		listingCount: 5
	};

	it('shows VRAM, release month and in-stock-of-listed, each with a screen-reader label', () => {
		const html = renderComponent(ProductRow, { group: row, onToggleCompare: () => {} });
		expect(html).toContain('12GB');
		expect(html).toContain('Mar 2025');
		expect(html).toContain('3 of 5');
		expect(html).toContain('VRAM:');
		expect(html).toContain('Released:');
		expect(html).toContain('Listings:');
	});

	it('labels the compare checkbox with what it does (U5)', () => {
		const html = renderComponent(ProductRow, { group: row, onToggleCompare: () => {} });
		expect(html).toContain('aria-label="Compare GeForce RTX 5070"');
		expect(html).toContain('title="Add to comparison"');
	});

	it('shows cores for a CPU and a dash when a figure is unknown', () => {
		const html = renderComponent(ProductRow, {
			group: { ...row, category: 'cpu', vramGb: null, cores: 8, launchDate: null }
		});
		expect(html).toContain('Cores:');
		expect(html).toContain('>8<');
		expect(html).toContain('Released: </span>—');
	});
	const fx = { rateDate: '2026-10-01', audPerUsd: 1.5, source: 'rba' };

	it('shows a toned whole-percent vs MSRP from lg up (Task 3)', () => {
		// 899 vs 549 x 1.5 x 1.1 = 905.85 -> within 2%: muted
		const near = renderComponent(ProductRow, { group: { ...row, msrpUsd: 549 }, fx });
		expect(near).toMatch(/data-testid="row-msrp"[^>]*>/);
		expect(near).toContain('−1%');
		expect(near).toContain('vs MSRP: ');
		// 899 vs 499 x 1.65 = 823.35 -> 9% over: warning
		const over = renderComponent(ProductRow, { group: { ...row, msrpUsd: 499 }, fx });
		expect(over).toMatch(/text-warning[^>]*>\+9%/);
		// 899 vs 599 x 1.65 = 988.35 -> 9% under: success
		const under = renderComponent(ProductRow, { group: { ...row, msrpUsd: 599 }, fx });
		expect(under).toMatch(/text-success[^>]*>−9%/);
	});

	it('shows "–" vs MSRP without an MSRP or a rate', () => {
		const html = renderComponent(ProductRow, { group: { ...row, msrpUsd: null }, fx });
		expect(html).toMatch(/vs MSRP: <\/span><span[^>]*>–</);
		const noFx = renderComponent(ProductRow, { group: { ...row, msrpUsd: 599 } });
		expect(noFx).toMatch(/vs MSRP: <\/span><span[^>]*>–</);
	});
});

describe('MsrpLine (Task 3)', () => {
	const fx = { rateDate: '2026-10-01', audPerUsd: 1.5, source: 'rba' };

	it('renders nothing when any input is missing', () => {
		expect(renderComponent(MsrpLine, { price: null, msrpUsd: 1099, fx })).not.toContain('MSRP');
		expect(renderComponent(MsrpLine, { price: 1700, msrpUsd: null, fx })).not.toContain('MSRP');
		expect(renderComponent(MsrpLine, { price: 1700, msrpUsd: 1099, fx: null })).not.toContain('MSRP');
	});

	it('states the delta, the AUD equivalent and an explanation toggle', () => {
		// 1099 x 1.65 = 1813.35; 1700 is 6% under
		const html = renderComponent(MsrpLine, { price: 1700, msrpUsd: 1099, fx });
		expect(html).toContain('6% under US launch MSRP');
		expect(html.replace(/<[^>]+>/g, '')).toContain('≈A$1,813 inc. GST');
		expect(html).toContain('aria-expanded="false"');
		expect(html).toMatch(/aria-controls="[^"]+"/);
		expect(html).toContain('aria-label="How the MSRP is converted"');
		// Every icon is decorative.
		const svgs = html.match(/<svg[^>]*>/g) ?? [];
		expect(svgs.length).toBe(2);
		for (const svg of svgs) expect(svg).toContain('aria-hidden="true"');
	});

	it('opens the explanation and closes it on Escape', async () => {
		const target = document.createElement('div');
		document.body.appendChild(target);
		const comp = mount(MsrpLine as never, { target, props: { price: 1700, msrpUsd: 1099, fx } });
		const button = target.querySelector('button')!;
		button.click();
		await tick();
		expect(button.getAttribute('aria-expanded')).toBe('true');
		const panel = target.querySelector(`#${button.getAttribute('aria-controls')}`)!;
		expect(panel.textContent).toContain('AUD/USD');
		expect(panel.textContent).toContain('GST');
		button.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(button.getAttribute('aria-expanded')).toBe('false');
		unmount(comp);
		target.remove();
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

describe('SegmentedControl (#5 item 5)', () => {
	it('is a labelled group of buttons whose pressed state is exposed', () => {
		const html = renderComponent(SegmentedControl, {
			label: 'Sort',
			options: [
				{ value: 'abs', label: '$ change' },
				{ value: 'pct', label: '% change' }
			],
			value: 'pct',
			onChange: () => {}
		});
		expect(html).toContain('role="group"');
		expect(html).toContain('aria-label="Sort"');
		expect(html).toMatch(/aria-pressed="false"[^>]*>\s*\$ change/);
		expect(html).toMatch(/aria-pressed="true"[^>]*>\s*% change/);
	});
});
