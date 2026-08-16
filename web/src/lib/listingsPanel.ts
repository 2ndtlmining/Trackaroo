import type { Series } from './server/repos';
import { deriveListingBrand } from './branding';
import type { StockStatus } from './types';

export interface ListingDisplay {
	listingId: number;
	brand: string;
	variantName: string | null;
	retailer: string;
	listingUrl: string;
	latestPrice: number | null;
	latestStock: StockStatus;
	inStock: boolean;
	firstSeen: string | null;
	lastSeen: string | null;
	selected: boolean;
}

export interface BrandGroup {
	brand: string;
	listings: ListingDisplay[];
	inStockCount: number;
	minPrice: number | null;
	maxPrice: number | null;
}

export interface PanelFilters {
	query: string;
	inStockOnly: boolean;
}

// One display row per retailer listing, derived from the detail-page series.
export function toListingDisplays(
	series: Series[],
	productBrand: string,
	selected: ReadonlySet<number>
): ListingDisplay[] {
	return series.map((s) => {
		const last = s.points.length > 0 ? s.points[s.points.length - 1] : null;
		return {
			listingId: s.listing.id,
			brand: deriveListingBrand(s.listing.variant_name, productBrand),
			variantName: s.listing.variant_name,
			retailer: s.listing.retailer,
			listingUrl: s.listing.listing_url,
			latestPrice: last?.price_aud ?? null,
			latestStock: last?.stock_status ?? 'unknown',
			inStock: last?.stock_status === 'in_stock',
			firstSeen: s.points.length > 0 ? s.points[0].snapshot_date : null,
			lastSeen: last?.snapshot_date ?? null,
			selected: selected.has(s.listing.id)
		};
	});
}

export function priceRange(listings: ListingDisplay[]): { min: number | null; max: number | null } {
	let min: number | null = null;
	let max: number | null = null;
	for (const l of listings) {
		if (l.latestPrice === null) continue;
		if (min === null || l.latestPrice < min) min = l.latestPrice;
		if (max === null || l.latestPrice > max) max = l.latestPrice;
	}
	return { min, max };
}

// Groups listings by derived brand, applies the free-text/in-stock filters,
// and sorts groups cheapest-in-stock first (groups with nothing in stock sink
// to the end, then alphabetical).
export function buildBrandGroups(
	series: Series[],
	productBrand: string,
	filters: PanelFilters,
	selected: ReadonlySet<number>
): BrandGroup[] {
	const displays = toListingDisplays(series, productBrand, selected);
	const q = filters.query.trim().toLowerCase();

	const visible = displays.filter((d) => {
		if (filters.inStockOnly && !d.inStock) return false;
		if (q) {
			const haystack = `${d.variantName ?? ''} ${d.retailer}`.toLowerCase();
			if (!haystack.includes(q)) return false;
		}
		return true;
	});

	const byBrand = new Map<string, ListingDisplay[]>();
	for (const d of visible) {
		const list = byBrand.get(d.brand);
		if (list) list.push(d);
		else byBrand.set(d.brand, [d]);
	}

	const groups: BrandGroup[] = [];
	for (const [brand, listings] of byBrand) {
		const { min, max } = priceRange(listings);
		groups.push({
			brand,
			listings,
			inStockCount: listings.filter((l) => l.inStock).length,
			minPrice: min,
			maxPrice: max
		});
	}

	groups.sort((a, b) => {
		if (a.minPrice === null && b.minPrice === null) {
			return a.brand.localeCompare(b.brand);
		}
		if (a.minPrice === null) return 1;
		if (b.minPrice === null) return -1;
		return a.minPrice - b.minPrice || a.brand.localeCompare(b.brand);
	});

	return groups;
}