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

export function formatUsd(value: number): string {
	return new Intl.NumberFormat('en-US', {
		style: 'currency',
		currency: 'USD',
		minimumFractionDigits: 0,
		maximumFractionDigits: 2
	}).format(value);
}

export function formatSignedAud(value: number): string {
	const sign = value > 0 ? '+' : value < 0 ? '−' : '';
	return `${sign}${formatAudFull(Math.abs(value))}`;
}

export function formatPct(value: number): string {
	const sign = value > 0 ? '+' : value < 0 ? '−' : '';
	return `${sign}${Math.abs(value).toFixed(1)}%`;
}

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

export function formatDate(dateStr: string): string {
	const date = new Date(`${dateStr}T00:00:00`);
	if (Number.isNaN(date.getTime())) return dateStr;
	return date.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function formatAxisLabel(dateStr: string): string {
	const date = new Date(`${dateStr}T00:00:00`);
	if (Number.isNaN(date.getTime())) return dateStr;
	return date.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' });
}

export function freshnessLabel(lastSnapshotAt: string | null, now: Date = new Date()): string {
	if (!lastSnapshotAt) return 'no data';
	const ageDays = Math.floor((now.getTime() - new Date(lastSnapshotAt).getTime()) / 86_400_000);
	if (ageDays <= 0) return 'today';
	if (ageDays === 1) return 'yesterday';
	return `${ageDays}d ago`;
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