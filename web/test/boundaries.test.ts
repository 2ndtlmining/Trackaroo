// #30: client code never imports server modules. #61: no source file under
// web/src (server or client, .ts or .svelte) grows past 350 lines.
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(__dirname, '..', 'src');

function walk(dir: string): string[] {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
		e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]
	);
}

const files = walk(SRC).filter((f) => /\.(ts|svelte)$/.test(f));
const isServerSide = (f: string) =>
	f.includes(`${path.sep}lib${path.sep}server${path.sep}`) ||
	/\+(page|layout)\.server\.ts$/.test(f) ||
	/\+server\.ts$/.test(f) ||
	/hooks\.server\.ts$/.test(f);

describe('boundaries (#30, #61)', () => {
	it('no client file imports $lib/server (alias or relative)', () => {
		const serverDir = path.join(SRC, 'lib', 'server');
		const specRe = /(?:\bfrom\s+|\bimport\s+|\bimport\s*\(\s*)['"]([^'"]+)['"]/g;
		const underServer = (p: string) => p === serverDir || p.startsWith(serverDir + path.sep);
		const offenders = files
			.filter((f) => !isServerSide(f))
			.filter((f) => {
				const text = fs.readFileSync(f, 'utf-8');
				for (const m of text.matchAll(specRe)) {
					const spec = m[1];
					let resolved: string | null = null;
					if (spec.startsWith('$lib/') || spec === '$lib') resolved = path.join(SRC, 'lib', spec.slice(5));
					else if (spec.startsWith('.')) resolved = path.resolve(path.dirname(f), spec);
					if (resolved && underServer(path.normalize(resolved))) return true;
				}
				return false;
			})
			.map((f) => path.relative(SRC, f));
		expect(offenders).toEqual([]);
	});

	it('no source file over 350 lines', () => {
		const big = files
			.map((f) => [path.relative(SRC, f), fs.readFileSync(f, 'utf-8').split('\n').length] as const)
			.filter(([, n]) => n > 350);
		expect(big).toEqual([]);
	});
});
