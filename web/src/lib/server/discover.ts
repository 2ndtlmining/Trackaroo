// Discovery report (#16): reads discovered_parts / discovery_conflicts /
// discovery_runs (written by discover.py) and records Track/Ignore decisions.
// Every reader tolerates a DB that predates the tables (returns empty data),
// so an old DB can never 500 the page or the nav badge.
import type { DB } from './db';
import type {
	DiscoverAction,
	DiscoverPageData,
	DiscoveredPart,
	DiscoveredStatus,
	DiscoveryConflict,
	DiscoveryRun
} from '$lib/types';

const ACTIONS: Record<DiscoverAction, { from: DiscoveredStatus[]; to: DiscoveredStatus }> = {
	ignore: { from: ['untracked', 'requested'], to: 'ignored' },
	unignore: { from: ['ignored'], to: 'untracked' },
	track: { from: ['untracked'], to: 'requested' },
	untrack: { from: ['requested'], to: 'untracked' }
};

export function isDiscoverAction(value: unknown): value is DiscoverAction {
	return typeof value === 'string' && Object.hasOwn(ACTIONS, value);
}

export function localIsoDate(d: Date = new Date()): string {
	const pad = (n: number) => String(n).padStart(2, '0');
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function hasTables(db: DB): boolean {
	const row = db
		.prepare(
			"SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name IN ('discovered_parts', 'discovery_conflicts', 'discovery_runs')"
		)
		.get() as { n: number };
	return row.n === 3;
}

function parseList(text: string | null): string[] {
	try {
		const v = JSON.parse(text ?? '[]');
		return Array.isArray(v) ? v.map(String) : [];
	} catch {
		return [];
	}
}

interface PartRow {
	id: number;
	category: 'cpu' | 'gpu';
	part_key: string;
	display_name: string;
	status: DiscoveredStatus;
	first_seen: string;
	last_seen: string;
	listing_count: number;
	retailers: string;
	min_price: number | null;
	min_price_url: string | null;
	sample_titles: string;
	suggested_row: string;
}

function toPart(r: PartRow): DiscoveredPart {
	return {
		id: r.id,
		category: r.category,
		partKey: r.part_key,
		displayName: r.display_name,
		status: r.status,
		firstSeen: r.first_seen,
		lastSeen: r.last_seen,
		listingCount: r.listing_count,
		retailers: r.retailers ? r.retailers.split(',') : [],
		minPrice: r.min_price,
		minPriceUrl: r.min_price_url,
		sampleTitles: parseList(r.sample_titles),
		suggestedRow: r.suggested_row
	};
}

function daysBefore(iso: string, days: number): string {
	const [y, m, d] = iso.split('-').map(Number);
	return localIsoDate(new Date(y, m - 1, d - days));
}

export function getDiscoverPage(db: DB, today: string): DiscoverPageData {
	const empty: DiscoverPageData = {
		lastRun: null,
		isStale: true,
		today,
		newThisWeek: 0,
		untracked: [],
		requested: [],
		ignored: [],
		conflicts: []
	};
	if (!hasTables(db)) return empty;
	const parts = (
		db.prepare('SELECT * FROM discovered_parts ORDER BY first_seen DESC, display_name').all() as PartRow[]
	).map(toPart);
	const run = db.prepare('SELECT * FROM discovery_runs ORDER BY id DESC LIMIT 1').get() as
		| {
				run_date: string;
				finished_at: string;
				catalogue_files: number;
				missing: string;
				unrecognised_count: number;
				unrecognised_samples: string;
		  }
		| undefined;
	const lastRun: DiscoveryRun | null = run
		? {
				runDate: run.run_date,
				finishedAt: run.finished_at,
				catalogueFiles: run.catalogue_files,
				missing: parseList(run.missing),
				unrecognisedCount: run.unrecognised_count,
				unrecognisedSamples: parseList(run.unrecognised_samples)
			}
		: null;
	const conflicts = (
		db
			.prepare(
				`SELECT c.listing_id, c.retailer, c.filed_product_id, p.model AS filed_model, c.title_key, c.reason, c.title
				 FROM discovery_conflicts c JOIN products p ON p.id = c.filed_product_id ORDER BY p.model, c.title`
			)
			.all() as Array<{
			listing_id: number;
			retailer: string;
			filed_product_id: number;
			filed_model: string;
			title_key: string | null;
			reason: string;
			title: string;
		}>
	).map(
		(c): DiscoveryConflict => ({
			listingId: c.listing_id,
			retailer: c.retailer,
			filedProductId: c.filed_product_id,
			filedModel: c.filed_model,
			titleKey: c.title_key,
			reason: c.reason,
			title: c.title
		})
	);
	const untracked = parts.filter((p) => p.status === 'untracked');
	const weekStart = daysBefore(today, 6);
	return {
		lastRun,
		isStale: !lastRun || lastRun.runDate !== today,
		today,
		newThisWeek: untracked.filter((p) => p.firstSeen >= weekStart).length,
		untracked,
		requested: parts.filter((p) => p.status === 'requested'),
		ignored: parts.filter((p) => p.status === 'ignored'),
		conflicts
	};
}

export function getDiscoverPendingCount(db: DB): number {
	try {
		if (!hasTables(db)) return 0;
		return (db.prepare("SELECT COUNT(*) AS n FROM discovered_parts WHERE status = 'untracked'").get() as { n: number }).n;
	} catch {
		return 0;
	}
}

export function applyDiscoverAction(
	db: DB,
	id: number,
	action: DiscoverAction,
	nowIso: string
): 'ok' | 'not-found' | 'invalid' {
	const row = db.prepare('SELECT status FROM discovered_parts WHERE id = ?').get(id) as
		| { status: DiscoveredStatus }
		| undefined;
	if (!row) return 'not-found';
	const rule = ACTIONS[action];
	if (!rule.from.includes(row.status)) return 'invalid';
	const marks = rule.from.map(() => '?').join(', ');
	const res = db
		.prepare(`UPDATE discovered_parts SET status = ?, decided_at = ? WHERE id = ? AND status IN (${marks})`)
		.run(rule.to, nowIso, id, ...rule.from);
	return res.changes === 0 ? 'invalid' : 'ok';
}
