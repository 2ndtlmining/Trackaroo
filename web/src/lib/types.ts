export type Category = 'cpu' | 'gpu';

// The four beyond scorptec/pccg have no scraper yet — the display layer is
// prepared ahead of them so adding one is a pipeline change, not a UI change
// (spec §7). Slugs must match what a future scraper writes to
// retailer_listings.retailer.
export type Retailer = 'scorptec' | 'pccg' | 'mwave' | 'umart' | 'centrecom' | 'ple';

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
	inStock?: boolean;
}

export type ListingSort = 'price-asc' | 'price-desc';

export type AlertChannel = 'discord' | 'email' | 'webhook';

export type DiscoveredStatus = 'untracked' | 'ignored' | 'requested' | 'tracked';
export type DiscoverAction = 'ignore' | 'unignore' | 'track' | 'untrack';

export interface DiscoveredPart {
	id: number;
	category: Category;
	partKey: string;
	displayName: string;
	status: DiscoveredStatus;
	firstSeen: string;
	lastSeen: string;
	listingCount: number;
	retailers: string[];
	minPrice: number | null;
	minPriceUrl: string | null;
	sampleTitles: string[];
	suggestedRow: string;
}

export interface DiscoveryConflict {
	listingId: number;
	retailer: string;
	filedProductId: number;
	filedModel: string;
	titleKey: string | null;
	reason: string;
	title: string;
}

export interface DiscoveryRun {
	runDate: string;
	finishedAt: string;
	catalogueFiles: number;
	missing: string[];
	unrecognisedCount: number;
	unrecognisedSamples: string[];
}

export interface DiscoverPageData {
	lastRun: DiscoveryRun | null;
	isStale: boolean;
	today: string;
	newThisWeek: number;
	untracked: DiscoveredPart[];
	requested: DiscoveredPart[];
	ignored: DiscoveredPart[];
	conflicts: DiscoveryConflict[];
}
