// Runs test/equivalence.test.ts against a read-only TEMP COPY of the real
// local DB (never the original file: #30 data-safety rule).
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '..', '..', 'db', 'trackaroo.db');
if (!fs.existsSync(src)) {
	console.log(`No ${src}; nothing to compare against.`);
	process.exit(0);
}
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-equiv-'));
const copy = path.join(dir, 'trackaroo.db');
fs.copyFileSync(src, copy);
for (const ext of ['-wal', '-shm']) if (fs.existsSync(src + ext)) fs.copyFileSync(src + ext, copy + ext);
try {
	execSync('npx vitest run test/equivalence.test.ts', {
		stdio: 'inherit',
		cwd: path.resolve(here, '..'),
		env: { ...process.env, TRACKAROO_EQUIV_DB: copy }
	});
} finally {
	fs.rmSync(dir, { recursive: true, force: true });
}
