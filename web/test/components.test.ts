import { describe, expect, it } from 'vitest';
import { mount, unmount } from 'svelte';
import Badge from '../src/lib/components/Badge.svelte';
import StatTile from '../src/lib/components/StatTile.svelte';
import PriceChange from '../src/lib/components/PriceChange.svelte';
import StockBadge from '../src/lib/components/StockBadge.svelte';
import Chip from '../src/lib/components/Chip.svelte';
import LatestListingTable from '../src/lib/components/LatestListingTable.svelte';
import type { LatestListing } from '../src/lib/server/repos';

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