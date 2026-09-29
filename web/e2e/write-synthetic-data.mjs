// Writes the deterministic synthetic snapshots (the same ones e2e/seed.mjs
// falls back to) as data/*.json files. CI has no data/ -- it is gitignored --
// and the vitest helper seeds from it (#13).
//   node e2e/write-synthetic-data.mjs ../data
import fs from 'node:fs';
import path from 'node:path';
import { buildSyntheticSources } from './seed.mjs';

const out = path.resolve(process.argv[2] ?? path.join('..', 'data'));
fs.mkdirSync(out, { recursive: true });
const existing = fs.readdirSync(out).filter((f) => f.endsWith('.json'));
if (existing.length) {
	// Never mix synthetic files into a real scrape history.
	console.error(`[synthetic] ${out} already holds ${existing.length} JSON file(s) - refusing`);
	process.exit(1);
}
const sources = buildSyntheticSources();
for (const { name, data } of sources) {
	fs.writeFileSync(path.join(out, name), JSON.stringify(data, null, 2));
}
console.log(`[synthetic] wrote ${sources.length} snapshot file(s) to ${out}`);
