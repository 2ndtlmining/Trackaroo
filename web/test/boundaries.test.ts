// #30: client code never imports server modules, and no server file grows
// past 350 lines.
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

describe('boundaries (#30)', () => {
	it('no client file imports $lib/server', () => {
		const offenders = files
			.filter((f) => !isServerSide(f))
			.filter((f) => /from\s+['"]\$lib\/server/.test(fs.readFileSync(f, 'utf-8')))
			.map((f) => path.relative(SRC, f));
		expect(offenders).toEqual([]);
	});

	it('no server file over 350 lines', () => {
		const big = files
			.filter((f) => f.includes(`${path.sep}lib${path.sep}server${path.sep}`))
			.map((f) => [path.relative(SRC, f), fs.readFileSync(f, 'utf-8').split('\n').length] as const)
			.filter(([, n]) => n > 350);
		expect(big).toEqual([]);
	});
});
