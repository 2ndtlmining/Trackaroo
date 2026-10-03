// Client-safe DTO types for alerts, FX, OzBargain and value (#61). Re-exported
// from $lib/models; import them from there. Types only, like models.ts.
import type { AlertChannel } from './types';

export interface AlertRow {
	id: number;
	product_id: number;
	target_price: number;
	channel: AlertChannel;
	notify_on_restock: number;
	active: number;
	last_notified_at: string | null;
	last_notified_price: number | null;
	created_at: string;
}

// Newest cached AUD per 1 USD (fx_rates), for converting launch MSRPs.
export interface FxRate {
	rateDate: string;
	audPerUsd: number;
	source: string;
}

// One OzBargain deal matched to a product (ozb_deals, #34). url is always the
// /node/<id> page, never a /goto/ redirect.
export interface OzbDeal {
	nodeId: number;
	title: string;
	url: string;
	priceAud: number | null;
	retailer: string | null;
	votesPos: number;
	votesNeg: number;
	postedAt: string | null;
	expired: boolean;
}

// Tracked product with its cheapest in-stock price on the latest snapshot
// date (null when nothing is in stock). Feeds the value maths (#33).
export interface ValueRow {
	id: number;
	name: string;
	model: string;
	vramGb: number | null;
	/** generation_tier: 'current', 'current-1', 'current-2' or null. */
	tier: string | null;
	price: number | null;
}

// How many tracked products have performance data and a price (#33 R6).
export interface ValueCoverage {
	tracked: number;
	withPerf: number;
	withoutPerf: number;
	withPerfAndPrice: number;
	/** Has performance data but no in-stock price today: left off the charts. */
	noPrice: number;
}
