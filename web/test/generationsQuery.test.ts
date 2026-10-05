import Database from 'better-sqlite3';
import { describe, expect, it } from 'vitest';
import { getTierLabels } from '../src/lib/server/queries/generations';

function db(withTable = true) {
	const d = new Database(':memory:');
	if (withTable) {
		d.exec(`CREATE TABLE generations (series_key TEXT PRIMARY KEY, line_id TEXT NOT NULL, label TEXT NOT NULL,
			position INTEGER NOT NULL, keep_all INTEGER NOT NULL DEFAULT 0)`);
		const ins = d.prepare('INSERT INTO generations VALUES (?, ?, ?, ?, ?)');
		ins.run('zen6', 'amd-cpu', 'Ryzen 10000 (Zen 6)', 0, 0);
		ins.run('zen5', 'amd-cpu', 'Ryzen 9000 (Zen 5)', 1, 0);
		ins.run('zen4', 'amd-cpu', 'Ryzen 7000 (Zen 4)', 2, 0);
		ins.run('zen3', 'amd-cpu', 'Ryzen 5000 (Zen 3)', 3, 0);
		ins.run('arc-b', 'intel-gpu', 'Arc B', 0, 1);
		ins.run('arc-a', 'intel-gpu', 'Arc A', 1, 1);
		ins.run('arc-x', 'intel-gpu', 'Arc X', 2, 1);
		ins.run('arc-w', 'intel-gpu', 'Arc W', 3, 1);
	}
	return d;
}

describe('getTierLabels', () => {
	it('maps positions to tiers per line', () => {
		expect(getTierLabels(db())['amd-cpu']).toEqual({
			current: 'Ryzen 10000 (Zen 6)',
			'current-1': 'Ryzen 9000 (Zen 5)',
			'current-2': 'Ryzen 7000 (Zen 4)'
		});
	});
	it('keeps position 2 as the current-2 label on a keep_all line', () => {
		expect(getTierLabels(db())['intel-gpu']['current-2']).toBe('Arc X');
	});
	it('returns {} on a DB without the table', () => {
		expect(getTierLabels(db(false))).toEqual({});
	});
});
