// The chart's accessible name (#27): a canvas says nothing to a screen reader,
// so the figures it draws are summarised in words.
import type { DailyLow } from './buySignals';
import { formatAud, formatDate } from './formats';

export function chartSummary(lows: DailyLow[], today: number | null): string {
	if (lows.length === 0) return 'Price history chart. No in-stock price recorded yet.';
	const prices = lows.map((p) => p.price);
	const min = Math.min(...prices);
	const max = Math.max(...prices);
	const span = `between ${formatDate(lows[0].date)} and ${formatDate(lows[lows.length - 1].date)}`;
	const range =
		min === max
			? `The cheapest in-stock price held at ${formatAud(min)} ${span}.`
			: `The cheapest in-stock price ranged from ${formatAud(min)} to ${formatAud(max)} ${span}.`;
	const now = today === null ? 'Nothing in stock today.' : `Today ${formatAud(today)}.`;
	return `Price history chart. ${range} ${now}`;
}
