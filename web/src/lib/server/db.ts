import Database from 'better-sqlite3';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Category, GenerationTier, ListingStatus, Retailer, StockStatus } from '../types';

export type DB = Database.Database;

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_DB_PATH = path.resolve(HERE, '..', '..', '..', '..', 'db', 'trackaroo.db');

export interface ProductRow {
	id: number;
	category: Category;
	brand: string;
	model: string;
	variant: string | null;
	vram_gb: number | null;
	cores: number | null;
	generation_tier: GenerationTier | null;
	tracked: number;
	last_snapshot_at: string | null;
	created_at: string;
}

export interface ListingRow {
	id: number;
	product_id: number;
	retailer: Retailer;
	variant_name: string | null;
	retailer_sku: string | null;
	listing_url: string;
	status: ListingStatus;
	first_seen_at: string;
	last_seen_at: string | null;
	last_snapshot_at: string | null;
}

export interface SnapshotRow {
	id: number;
	retailer_listing_id: number;
	snapshot_date: string;
	price_aud: number;
	stock_status: StockStatus;
	scraped_at: string;
}

export interface SpecRow {
	spec_id: number;
	product_id: number;
	source: string;
	source_record_key: string;
	category: Category;
	architecture: string | null;
	generation: string | null;
	launch_date: string | null;
	launch_msrp_usd: number | null;
	vram_gb: number | null;
	memory_bus_width_bit: number | null;
	memory_type: string | null;
	tdp_watts: number | null;
	core_count: number | null;
	thread_count: number | null;
	base_clock_mhz: number | null;
	boost_clock_mhz: number | null;
	socket: string | null;
	cache_l3_mb: number | null;
	gpu_die: string | null;
	bus_interface: string | null;
	memory_bandwidth_gbps: number | null;
	memory_clock_mhz: number | null;
	process_nm: number | null;
	foundry: string | null;
	codename: string | null;
	l1_cache_kb: number | null;
	l2_cache_mb: number | null;
	memory_speed_mhz: number | null;
	memory_channels: number | null;
	memory_types: string | null;
	integrated_graphics: string | null;
	raw_json: string;
	last_synced_at: string;
}

export interface OpenOptions {
	readonly?: boolean;
	fileMustExist?: boolean;
}

export function openDatabase(file: string, options: OpenOptions = {}): DB {
	const readonly = options.readonly ?? true;
	const db = new Database(file, {
		readonly,
		fileMustExist: options.fileMustExist ?? readonly
	});
	db.pragma('busy_timeout = 5000');
	db.pragma('foreign_keys = ON');
	return db;
}

let cached: DB | null = null;

export function getDb(): DB {
	if (!cached) {
		const file = process.env.TRACKAROO_DB ?? DEFAULT_DB_PATH;
		cached = openDatabase(file);
	}
	return cached;
}

export function closeDb(): void {
	if (cached) {
		cached.close();
		cached = null;
	}
}
