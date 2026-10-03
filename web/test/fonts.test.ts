import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const css = fs.readFileSync(path.join(root, 'src', 'app.css'), 'utf-8');

const FILES = [
	'bricolage-grotesque-latin-700-normal.woff2',
	'bricolage-grotesque-latin-800-normal.woff2',
	'ibm-plex-sans-latin-400-normal.woff2',
	'ibm-plex-sans-latin-500-normal.woff2',
	'ibm-plex-sans-latin-600-normal.woff2',
	'ibm-plex-mono-latin-500-normal.woff2',
	'ibm-plex-mono-latin-600-normal.woff2'
];

function walk(dir: string): string[] {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
		const p = path.join(dir, e.name);
		return e.isDirectory() ? walk(p) : [p];
	});
}

describe('self-hosted fonts (#22)', () => {
	it('never references Google Fonts hosts in src or static', () => {
		for (const dir of ['src', 'static']) {
			for (const f of walk(path.join(root, dir))) {
				if (/\.(woff2|png|ico)$/.test(f)) continue;
				const text = fs.readFileSync(f, 'utf-8');
				expect(text, f).not.toContain('fonts.googleapis.com');
				expect(text, f).not.toContain('fonts.gstatic.com');
			}
		}
	});

	it.each(FILES)('declares @font-face for %s with swap', (file) => {
		const blocks = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => m[1]);
		const block = blocks.find((b) => b.includes(`/fonts/${file}`));
		expect(block, file).toBeTruthy();
		expect(block).toContain(`src: url('/fonts/${file}') format('woff2')`);
		expect(block).toMatch(/font-display:\s*swap/);
	});

	it.each(FILES)('ships %s', (file) => {
		expect(fs.existsSync(path.join(root, 'static', 'fonts', file))).toBe(true);
	});

	it('keeps the fallback stacks after the web fonts', () => {
		expect(css).toMatch(
			/--font-sans:\s*'IBM Plex Sans',\s*-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;/
		);
		expect(css).toMatch(
			/--font-mono:\s*'IBM Plex Mono',\s*'SF Mono', 'Cascadia Code', 'JetBrains Mono', Consolas, 'Liberation Mono', Menlo, monospace;/
		);
		expect(css).toContain("--font-display: 'Bricolage Grotesque', var(--font-sans);");
	});
});
