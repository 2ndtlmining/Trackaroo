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