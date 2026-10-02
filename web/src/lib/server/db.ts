import Database from 'better-sqlite3';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { ListingRow, ProductRow, SnapshotRow, SpecRow } from '../models';
export type { ListingRow, ProductRow, SnapshotRow, SpecRow };

export type DB = Database.Database;

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_DB_PATH = path.resolve(HERE, '..', '..', '..', '..', 'db', 'trackaroo.db');

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

// The dashboard is read-only by default (getDb), but user actions such as
// arming a price alert need to write. This is a separate read-write connection
// to the same file — WAL mode keeps it safe alongside the read connection and
// the pipeline's writer. It requires the DB file to already exist (the web
// never creates the database).
let writeCached: DB | null = null;

export function getWriteDb(): DB {
	if (!writeCached) {
		const file = process.env.TRACKAROO_DB ?? DEFAULT_DB_PATH;
		writeCached = openDatabase(file, { readonly: false, fileMustExist: true });
	}
	return writeCached;
}
