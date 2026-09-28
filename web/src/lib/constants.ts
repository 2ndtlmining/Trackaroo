// Shared runtime constants used by both server and client code.
// Kept out of $lib/server so client components can import them without
// pulling a server-only module into the browser bundle.
export const MIN_HISTORY_POINTS = 3;

// Mirrors config.STALE_LISTING_DAYS: a listing unseen this many days before its
// retailer's latest snapshot is treated as gone even before the pipeline's
// check_stale_listings flips its status (#4).
export const STALE_LISTING_DAYS = 7;
