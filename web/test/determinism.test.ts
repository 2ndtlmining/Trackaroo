import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');

function sources(dir: string): string[] {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
		const p = path.join(dir, e.name);
		if (e.isDirectory()) return sources(p);
		return /\.(ts|svelte)$/.test(e.name) ? [p] : [];
	});
}

// Server-rendered text must equal the hydrated text. Locale-dependent
// formatting (Node's ICU says "Sept", browsers "Sep"; toLocaleString() with no
// locale follows the viewer's machine) breaks that (29-Sep follow-up).
describe('no locale-dependent date or number text', () => {
	it.each(sources(SRC).map((f) => [path.relative(SRC, f), f]))('%s', (_rel, file) => {
		const text = fs.readFileSync(file as string, 'utf-8');
		expect(text).not.toMatch(/toLocaleDateString|toLocaleTimeString/);
		expect(text).not.toMatch(/\.toLocaleString\(\s*\)/);
	});
});
