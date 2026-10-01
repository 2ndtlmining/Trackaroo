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

describe('USD amounts are always labelled (U3, #27 item 4)', () => {
	it('launch_msrp_usd only ever reaches the page through formatUsd', () => {
		for (const file of sources(SRC)) {
			const text = fs.readFileSync(file, 'utf-8');
			// formatAud(... launch_msrp_usd ...) or a raw {…launch_msrp_usd} interpolation
			expect(text, file).not.toMatch(/formatAud\([^)]*launch_msrp_usd/);
			expect(text, file).not.toMatch(/\{[^}]*\.launch_msrp_usd\s*\}/);
		}
	});
});
