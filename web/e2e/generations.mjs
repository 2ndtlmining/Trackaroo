// Fills the generations table the way seed.py does, from db/generations.toml.
// The web CI job has no Python, so the e2e DB reads the toml itself (#17).
import fs from 'node:fs';
import path from 'node:path';
import { parse as parseToml } from 'smol-toml';

export function seedGenerations(db, webRoot) {
	const text = fs.readFileSync(path.resolve(webRoot, '..', 'db', 'generations.toml'), 'utf-8');
	const ins = db.prepare(
		'INSERT OR REPLACE INTO generations (series_key, line_id, label, position, keep_all) VALUES (?, ?, ?, ?, ?)'
	);
	for (const line of parseToml(text).line) {
		line.series.forEach((s, i) => ins.run(s.key, line.id, s.label, i, line.keep_all ? 1 : 0));
	}
}
