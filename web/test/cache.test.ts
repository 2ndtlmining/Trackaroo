import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import { openDatabase } from '../src/lib/server/db';
import { memo, _resetMemo } from '../src/lib/server/cache';

function tempDb() {
	const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'memo-')), 't.db');
	const w = new Database(file);
	w.pragma('journal_mode = WAL');
	w.exec('CREATE TABLE t (v INTEGER); INSERT INTO t VALUES (1);');
	return { file, w };
}

describe('memo (#28)', () => {
	it('computes once while the DB is unchanged', () => {
		_resetMemo();
		const { file } = tempDb();
		const db = openDatabase(file);
		let calls = 0;
		memo(db, 'k', () => ++calls);
		memo(db, 'k', () => ++calls);
		expect(calls).toBe(1);
	});

	it('recomputes after another connection commits (pipeline or alert write)', () => {
		_resetMemo();
		const { file, w } = tempDb();
		const db = openDatabase(file);
		const read = () => memo(db, 'sum', () => (db.prepare('SELECT SUM(v) AS s FROM t').get() as { s: number }).s);
		expect(read()).toBe(1);
		w.exec('INSERT INTO t VALUES (41)');
		expect(read()).toBe(42);
	});
});
