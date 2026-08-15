export type Category = 'cpu' | 'gpu';

export type Retailer = 'scorptec' | 'pccg' | 'mwave';

export type GenerationTier = 'current' | 'current-1' | 'current-2';

export type ListingStatus = 'active' | 'delisted' | 'stale';

export type StockStatus = 'in_stock' | 'out_of_stock' | 'preorder' | 'unknown';

export type ChangeDirection = 'up' | 'down' | 'flat' | 'stale' | 'insufficient';

export interface ListingFilters {
	category?: Category;
	retailer?: Retailer;
	brand?: string;
	generation_tier?: GenerationTier;
	query?: string;
	sort?: ListingSort;
}

export type ListingSort = 'price-asc' | 'price-desc';
