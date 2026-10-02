import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

// Owner rule: no emojis anywhere in the dashboard; icons come from
// @lucide/svelte. Strict on purpose (controller ruling R3): arrows such as
// U+2197 count as pictographic too, so use the ArrowUpRight icon instead.
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const PICTOGRAPHIC = /\p{Extended_Pictographic}/u;

function sources(dir: string): string[] {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
		const p = path.join(dir, e.name);
		if (e.isDirectory()) return sources(p);
		return /\.(ts|svelte)$/.test(e.name) ? [p] : [];
	});
}

describe('no emojis in web/src', () => {
	it('no .svelte or .ts file contains an Extended_Pictographic character', () => {
		const hits: string[] = [];
		for (const file of sources(SRC)) {
			fs.readFileSync(file, 'utf-8')
				.split(/\r?\n/)
				.forEach((line, i) => {
					const m = PICTOGRAPHIC.exec(line);
					if (m) {
						const cp = m[0].codePointAt(0)!.toString(16).toUpperCase().padStart(4, '0');
						hits.push(`${path.relative(SRC, file)}:${i + 1} U+${cp}`);
					}
				});
		}
		expect(hits).toEqual([]);
	});
});
