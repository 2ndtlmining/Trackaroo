import type { Series } from './models';
import { deriveListingBrand } from './branding';
import type { StockStatus } from './types';
import { STALE_LISTING_DAYS } from './constants';

export interface ListingDisplay {
	listingId: number;
	brand: string;
	variantName: string | null;
	retailer: string;
	listingUrl: string;
	latestPrice: number | null;
	latestStock: StockStatus;
	// The listing was confirmed delisted (retailer_listings.status = 'delisted').
	// Its last snapshot is stale, so inStock is forced false regardless of it.
	delisted: boolean;
	// Unseen for STALE_LISTING_DAYS+ or marked stale by the pipeline. Not buyable.
	stale: boolean;
	inStock: boolean;
	firstSeen: string | null;
	lastSeen: string | null;
	selected: boolean;
}

// One display row per retailer listing, derived from the detail-page series.
export function toListingDisplays(
	series: Series[],
	productBrand: string,
	selected: ReadonlySet<number>,
	retailerLatest: Record<string, string> = {}
): ListingDisplay[] {
	return series.map((s) => {
		const last = s.points.length > 0 ? s.points[s.points.length - 1] : null;
		const delisted = s.listing.status === 'delisted';
		const lastSeen = last?.snapshot_date ?? null;
		const retailerLast = retailerLatest[s.listing.retailer];
		const unseenTooLong =
			lastSeen !== null &&
			retailerLast !== undefined &&
			(Date.parse(retailerLast) - Date.parse(lastSeen)) / 86_400_000 > STALE_LISTING_DAYS;
		const stale = !delisted && (s.listing.status === 'stale' || unseenTooLong);
		return {
			listingId: s.listing.id,
			brand: deriveListingBrand(s.listing.variant_name, productBrand),
			variantName: s.listing.variant_name,
			retailer: s.listing.retailer,
			listingUrl: s.listing.listing_url,
			latestPrice: last?.price_aud ?? null,
			latestStock: last?.stock_status ?? 'unknown',
			delisted,
			stale,
			inStock: !delisted && !stale && last?.stock_status === 'in_stock',
			firstSeen: s.points.length > 0 ? s.points[0].snapshot_date : null,
			lastSeen,
			selected: selected.has(s.listing.id)
		};
	});
}

// Delisted and stale listings are skipped: their last price is not trustworthy,
// not buyable, and must not skew the group's price range or cheapest-first
// sort order.
export function priceRange(listings: ListingDisplay[]): { min: number | null; max: number | null } {
	let min: number | null = null;
	let max: number | null = null;
	for (const l of listings) {
		if (l.delisted || l.stale || l.latestPrice === null) continue;
		if (min === null || l.latestPrice < min) min = l.latestPrice;
		if (max === null || l.latestPrice > max) max = l.latestPrice;
	}
	return { min, max };
}
