import { describe, expect, it } from 'vitest';
import { mount, unmount } from 'svelte';
import Badge from '../src/lib/components/Badge.svelte';
import StatTile from '../src/lib/components/StatTile.svelte';
import PriceChange from '../src/lib/components/PriceChange.svelte';
import StockBadge from '../src/lib/components/StockBadge.svelte';
import Chip from '../src/lib/components/Chip.svelte';
import LatestListingTable from '../src/lib/components/LatestListingTable.svelte';
import SpecPanel from '../src/lib/components/SpecPanel.svelte';
import type { LatestListing } from '../src/lib/server/repos';
import type { SpecRow } from '../src/lib/server/db';

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
});