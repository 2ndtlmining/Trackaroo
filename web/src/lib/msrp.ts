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
