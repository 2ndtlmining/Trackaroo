import { formatShortDate, formatUsd } from './formats';
import type { FxRate } from './models';

// Australian GST, added on top of the converted US launch price: a US MSRP
// excludes sales tax, an AU shelf price includes it.
export const GST = 0.1;

// What a product's US launch MSRP is worth in today's AUD, GST included.
// Null unless both inputs are present and positive.
export function msrpAud(msrpUsd: number | null, fx: FxRate | null): number | null {
	if (msrpUsd === null || fx === null) return null;
	if (!(msrpUsd > 0) || !(fx.audPerUsd > 0)) return null;
	return msrpUsd * fx.audPerUsd * (1 + GST);
}

// (price - MSRP) / MSRP as a fraction: negative means under MSRP.
export function msrpDelta(price: number | null, msrpAudValue: number | null): number | null {
	if (price === null || msrpAudValue === null) return null;
	if (!(price > 0) || !(msrpAudValue > 0)) return null;
	return (price - msrpAudValue) / msrpAudValue;
}

const SOURCE_LABELS: Record<string, string> = { rba: 'RBA', frankfurter: 'ECB' };

// The working behind msrpAud, for a tooltip. formatShortDate omits the year,
// so it is appended from the rate date.
export function msrpExplanation(msrpUsd: number, fx: FxRate): string {
	const source = SOURCE_LABELS[fx.source] ?? fx.source;
	const year = fx.rateDate.slice(0, 4);
	return `${formatUsd(msrpUsd)} × ${fx.audPerUsd.toFixed(4)} AUD/USD (${source}, ${formatShortDate(fx.rateDate)} ${year}) + ${Math.round(GST * 100)}% GST`;
}

// Presentation of msrpDelta (Task 3). Within 2% either way reads as "at MSRP"
// (muted), the same neutral band the vs-average cue uses.
export type MsrpTone = 'under' | 'near' | 'over';
const NEAR = 0.02;

export function msrpTone(delta: number): MsrpTone {
	if (delta <= -NEAR) return 'under';
	if (delta >= NEAR) return 'over';
	return 'near';
}

// Existing tokens only: success when under, muted when near, warning when over.
export const MSRP_TONE_CLASS: Record<MsrpTone, string> = {
	under: 'text-success',
	near: 'text-text-muted',
	over: 'text-warning'
};

// The whole percent every MSRP label prints, and the one the Below MSRP filter
// must agree with: a delta that rounds to 0% is "at MSRP", not below it.
function wholePct(delta: number): number {
	return Math.round(Math.abs(delta) * 100);
}

// A signed whole percent ("−3%", "+12%", "0%"), or "–" when unknown.
export function formatMsrpDelta(delta: number | null): string {
	if (delta === null) return '–';
	const pct = wholePct(delta);
	if (pct === 0) return '0%';
	return `${delta < 0 ? '−' : '+'}${pct}%`;
}

// "3% under US launch MSRP", "12% over US launch MSRP", "At US launch MSRP".
export function msrpPhrase(delta: number): string {
	const pct = wholePct(delta);
	if (pct === 0) return 'At US launch MSRP';
	return `${pct}% ${delta < 0 ? 'under' : 'over'} US launch MSRP`;
}

// For /deals?below_msrp=1: under MSRP by at least the 1% the label can show.
export function isBelowMsrp(price: number | null, msrpUsd: number | null, fx: FxRate | null): boolean {
	const delta = msrpDelta(price, msrpAud(msrpUsd, fx));
	return delta !== null && delta < 0 && wholePct(delta) > 0;
}
