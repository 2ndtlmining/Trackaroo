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

// --up / --down mean "price rose / fell". Status (stale, missing, error) has
// its own tokens, so a stale banner can never render in the "price fell"
// green again (#24).
const PRICE_DIRECTION_FILES = new Set([
	'lib/offers.ts',
	'lib/components/Badge.svelte',
	'lib/components/ProductHeadline.svelte'
]);

describe('colour semantics (#24)', () => {
	it.each(sources(SRC).map((f) => [path.relative(SRC, f).replaceAll('\\', '/')]))(
		'%s uses up/down only for price direction and no faded muted text',
		(rel) => {
			const text = fs.readFileSync(path.join(SRC, rel), 'utf-8');
			if (!PRICE_DIRECTION_FILES.has(rel)) {
				expect(text).not.toMatch(/\b(text|bg|border)-(up|down)\b/);
			}
			expect(text).not.toMatch(/text-text-muted\/\d+/);
			expect(text).not.toMatch(/\btext-stale\b/);
		}
	);
});
