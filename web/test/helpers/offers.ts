import type { ListingDisplay } from '../../src/lib/offers';

export function offer(overrides: Partial<ListingDisplay> = {}): ListingDisplay {
	return {
		listingId: 1,
		brand: 'ASUS',
		variantName: 'ASUS TUF RTX 5070 Ti OC 16GB',
		retailer: 'scorptec',
		listingUrl: 'https://example.com/1',
		latestPrice: 1299,
		latestStock: 'in_stock',
		delisted: false,
		inStock: true,
		firstSeen: '2026-03-12',
		lastSeen: '2026-08-23',
		selected: false,
		...overrides
	};
}
