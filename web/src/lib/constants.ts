// Shared runtime constants used by both server and client code.
// Kept out of $lib/server so client components can import them without
// pulling a server-only module into the browser bundle.
export const MIN_HISTORY_POINTS = 3;

// Mirrors config.STALE_LISTING_DAYS: a listing unseen this many days before its
// retailer's latest snapshot is treated as gone even before the pipeline's
// check_stale_listings flips its status (#4).
export const STALE_LISTING_DAYS = 7;

// /deals floors (owner decision 28-Sep-2026, #6): a deal must be at least this
// far below its 30-day average in BOTH percent and dollars.
export const DEAL_MIN_PCT = 2;
export const DEAL_MIN_AUD = 10;
// An all-time low only counts if the price was at least this much higher at
// some point in the window -- a flat line is not a drop.
export const EARNED_LOW_RISE_PCT = 3;
