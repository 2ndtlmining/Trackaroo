import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const STATIC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'static');

function pngSize(file: string): { width: number; height: number } {
	const buf = fs.readFileSync(path.join(STATIC, file));
	expect(buf.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
	expect(buf.subarray(12, 16).toString('ascii')).toBe('IHDR');
	return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

describe('installable icons (#25)', () => {
	it.each([
		['icon-192.png', 192],
		['icon-512.png', 512],
		['icon-maskable-512.png', 512],
		['apple-touch-icon.png', 180]
	])('%s is a %ipx PNG', (file, size) => {
		expect(pngSize(file)).toEqual({ width: size, height: size });
	});

	it('the manifest names the app and lists a maskable icon', () => {
		const m = JSON.parse(fs.readFileSync(path.join(STATIC, 'manifest.webmanifest'), 'utf-8'));
		expect(m.short_name).toBe('Trackaroo');
		expect(m.display).toBe('standalone');
		expect(m.start_url).toBe('/');
		expect(m.theme_color).toMatch(/^#[0-9a-f]{6}$/i);
		expect(m.background_color).toMatch(/^#[0-9a-f]{6}$/i);
		const sizes = m.icons.map((i: { sizes: string }) => i.sizes);
		expect(sizes).toContain('192x192');
		expect(sizes).toContain('512x512');
		expect(m.icons.some((i: { purpose?: string }) => i.purpose === 'maskable')).toBe(true);
		for (const icon of m.icons) {
			expect(fs.existsSync(path.join(STATIC, icon.src.replace(/^\//, '')))).toBe(true);
		}
	});
});
