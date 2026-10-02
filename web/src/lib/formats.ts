function formatAudFull(value: number): string {
	return new Intl.NumberFormat('en-AU', {
		style: 'currency',
		currency: 'AUD',
		minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
		maximumFractionDigits: 2
	}).format(value);
}

export function formatAud(value: number): string {
	return formatAudFull(value);
}

// Launch MSRPs are US dollars. Printed as "$1,999" beside AUD prices they read
// as AUD -- "$1,999" next to "$7,499" on the RTX 5090 page (U3). The prefix
// is part of the value so no caller can forget it.
export function formatUsd(value: number): string {
	const n = new Intl.NumberFormat('en-US', {
		style: 'currency',
		currency: 'USD',
		minimumFractionDigits: 0,
		maximumFractionDigits: 2
	}).format(value);
	return `US${n}`;
}

export function formatSignedAud(value: number): string {
	const sign = value > 0 ? '+' : value < 0 ? '−' : '';
	return `${sign}${formatAudFull(Math.abs(value))}`;
}

export function formatPct(value: number): string {
	const sign = value > 0 ? '+' : value < 0 ? '−' : '';
	return `${sign}${Math.abs(value).toFixed(1)}%`;
}

// First-to-last change of a price series, for a sparkline's label (#23):
// 'down 4%', 'up 3%', or 'flat' when it rounds to 0%. Null under two points.
export function formatTrend(values: number[]): string | null {
	if (values.length < 2 || values[0] <= 0) return null;
	const pct = Math.round(((values[values.length - 1] - values[0]) / values[0]) * 100);
	if (pct === 0) return 'flat';
	return `${pct > 0 ? 'up' : 'down'} ${Math.abs(pct)}%`;
}

// How old is it? One rule (#30):
//  - date-only values ('YYYY-MM-DD'): daysBehindToday + stalenessLabel
//  - true timestamps: formatRelative
//  - the product page's "Updated ..." stamp: updatedLabel, which agrees with
//    the stale banner's day count.
export function formatRelative(iso: string | null, now: Date = new Date()): string {
	if (!iso) return 'never';
	const then = new Date(iso).getTime();
	const diffMs = now.getTime() - then;
	if (diffMs < 60_000) return 'just now';
	const minutes = Math.floor(diffMs / 60_000);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 7) return `${days}d ago`;
	const weeks = Math.floor(days / 7);
	if (weeks < 5) return `${weeks}w ago`;
	const months = Math.floor(days / 30);
	return `${months}mo ago`;
}

// Fixed English month abbreviations. Intl's en-AU data says "Sept" in Node but
// browsers can say "Sep"; the server and the browser rendering different text
// is a hydration mismatch (29-Sep follow-up). A table cannot drift.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const;

// 'YYYY-MM-DD' (optionally followed by a time) -> [year, month 1-12, day].
function dateParts(iso: string): [number, number, number] | null {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
	if (!m) return null;
	const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
	if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
	return [y, mo, d];
}

export function formatDate(dateStr: string): string {
	const p = dateParts(dateStr);
	return p ? `${p[2]} ${MONTHS[p[1] - 1]} ${p[0]}` : dateStr;
}

export function formatShortDate(isoDate: string): string {
	const p = dateParts(isoDate);
	return p ? `${p[2]} ${MONTHS[p[1] - 1]}` : isoDate;
}

export function formatMonthYear(isoDate: string): string {
	const p = dateParts(isoDate);
	return p ? `${MONTHS[p[1] - 1]} ${p[0]}` : isoDate;
}

// uPlot x values are UTC-midnight milliseconds (PriceChart builds them with
// `${date}T00:00:00Z`), so read them back in UTC too.
export function formatChartTick(ts: number): string {
	const d = new Date(ts);
	return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

// Snapshots are dated, not timed: comparing a 'YYYY-MM-DD' against now() made
// every row say "updated just now" (28-Sep finding). Whole days only.
export function formatSeenDate(isoDate: string, today: string): string {
	const days = Math.round((Date.parse(today) - Date.parse(isoDate)) / 86_400_000);
	if (days <= 0) return 'today';
	if (days === 1) return 'yesterday';
	if (days < 7) return `${days} days ago`;
	return formatShortDate(isoDate);
}

// The calendar date in Melbourne, whatever the server's or browser's timezone:
// sale-event badges flip at AU midnight, not UTC midnight.
export function melbourneTodayIso(now: Date = new Date()): string {
	return new Intl.DateTimeFormat('en-CA', {
		timeZone: 'Australia/Melbourne',
		year: 'numeric',
		month: '2-digit',
		day: '2-digit'
	}).format(now);
}

export function todayIso(now: Date = new Date()): string {
	const y = now.getFullYear();
	const m = String(now.getMonth() + 1).padStart(2, '0');
	const d = String(now.getDate()).padStart(2, '0');
	return `${y}-${m}-${d}`;
}

export function stockLabel(stock: string): string {
	switch (stock) {
		case 'in_stock':
			return 'In stock';
		case 'out_of_stock':
			return 'Out of stock';
		case 'preorder':
			return 'Preorder';
		default:
			return 'Unknown';
	}
}

export function formatBytes(bytes: number): string {
	if (!bytes) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB'];
	const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
	const value = bytes / 1024 ** i;
	return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatBandwidth(gbps: number | null): string | null {
	if (gbps === null) return null;
	if (gbps >= 1000) return `${(gbps / 1000).toFixed(2)} TB/s`;
	return `${gbps.toFixed(0)} GB/s`;
}

export function formatProcess(nm: number | null, foundry: string | null): string | null {
	if (nm === null && foundry === null) return null;
	const nmStr = nm !== null ? `${Number.isInteger(nm) ? nm.toFixed(0) : nm.toFixed(1)} nm` : '';
	return [foundry, nmStr].filter(Boolean).join(' ') || null;
}

export function formatCacheMb(mb: number | null): string | null {
	if (mb === null) return null;
	return `${Number.isInteger(mb) ? mb.toFixed(0) : mb.toFixed(1)} MB`;
}

export function formatCacheKb(kb: number | null): string | null {
	if (kb === null) return null;
	return `${Number.isInteger(kb) ? kb.toFixed(0) : kb.toFixed(1)} KB`;
}

export function formatMhz(mhz: number | null): string | null {
	if (mhz === null) return null;
	return `${Number.isInteger(mhz) ? mhz.toFixed(0) : mhz.toFixed(1)} MHz`;
}

// Short/known tokens that should render fully uppercase (brands, acronyms that
// arrive lowercase from Scorptec's all-lowercase names). "ti" is intentionally
// NOT here — NVIDIA's suffix renders as "Ti".
const UPPER_WORDS = new Set(['amd', 'asus', 'evga', 'zotac', 'msi', 'rtx', 'gtx', 'oc', 'rgb', 'argb', 'xt', 'xtx']);

// Unit/acronym prefixes glued to a number ("gddr7" -> "GDDR7", "8gb" -> "8GB").
const PREFIX_WORDS = new Set(['gddr', 'gb', 'tb', 'g', 'w', 'k', 'm', 'mb', 'hz', 'ghz', 'mhz', 'vram', 'cu']);

// Display-only title-casing for retailer-provided variant names. Only words
// that are currently ENTIRELY lowercase are touched, so already-cased tokens
// ("RTX", "GDDR7", "GeForce") are left alone. Known acronyms uppercase fully
// ("rtx" -> "RTX", "oc" -> "OC"); other words capitalise their first letter
// and uppercase any letters following a digit ("5600x" -> "5600X",
// "7800x3d" -> "7800X3D", "gddr7" -> "GDDR7").
export function titleCase(name: string | null): string {
	if (!name) return '';
	return name.replace(/\b[a-z0-9]+\b/g, (token) => {
		if (UPPER_WORDS.has(token)) return token.toUpperCase();
		let out: string;
		const prefix = token.match(/^([a-z]+)(\d.*)$/);
		if (prefix && PREFIX_WORDS.has(prefix[1])) {
			out = prefix[1].toUpperCase() + prefix[2];
		} else {
			out = token.charAt(0).toUpperCase() + token.slice(1);
		}
		const digitIdx = out.search(/\d/);
		if (digitIdx !== -1 && /[a-z]/.test(out.slice(digitIdx + 1))) {
			out = out.slice(0, digitIdx + 1) + out.slice(digitIdx + 1).toUpperCase();
		}
		return out;
	});
}
/**
 * How many whole days behind today a snapshot date is.
 *
 * `snapshotDate` is a plain 'YYYY-MM-DD' calendar date, not a timestamp, so
 * this compares calendar days in local time rather than subtracting instants —
 * a snapshot taken this morning and one taken last night are both "today".
 *
 * Returns null when there is no date to compare, and never returns a negative
 * number (a clock skew that puts the DB "ahead" is not staleness).
 */
export function daysBehindToday(snapshotDate: string | null, now: Date = new Date()): number | null {
	if (!snapshotDate) return null;
	const snap = new Date(`${snapshotDate}T00:00:00`);
	if (Number.isNaN(snap.getTime())) return null;
	const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
	const diff = Math.round((today.getTime() - snap.getTime()) / 86_400_000);
	return diff > 0 ? diff : 0;
}

/** Human phrasing for a staleness gap, e.g. "1 day behind" / "3 days behind". */
export function stalenessLabel(days: number): string {
	return days === 1 ? '1 day behind' : `${days} days behind`;
}

/**
 * The product page's "Updated ..." stamp (#30). Same local day: relative time
 * ("Updated 25m ago"). Earlier: whole calendar days, the same count the stale
 * banner uses (daysBehindToday), so the page never says "2w ago" next to
 * "20 days behind".
 */
export function updatedLabel(lastSnapshotAt: string | null, now: Date = new Date()): string {
	if (!lastSnapshotAt) return 'Never updated';
	const then = new Date(lastSnapshotAt);
	if (Number.isNaN(then.getTime())) return 'Never updated';
	const localDate = `${then.getFullYear()}-${String(then.getMonth() + 1).padStart(2, '0')}-${String(then.getDate()).padStart(2, '0')}`;
	const days = daysBehindToday(localDate, now) ?? 0;
	if (days === 0) return `Updated ${formatRelative(lastSnapshotAt, now)}`;
	return days === 1 ? 'Updated 1 day ago' : `Updated ${days} days ago`;
}
