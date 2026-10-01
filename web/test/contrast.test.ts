import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

// Reads the colour tokens straight from app.css, so a token edit that breaks
// WCAG contrast fails CI (#24). Only solid #rrggbb tokens are measured; that is
// why the -soft backgrounds are solid colours rather than rgba().
const css = fs.readFileSync(
	path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'app.css'),
	'utf-8'
);

function tokens(block: string): Record<string, string> {
	const out: Record<string, string> = {};
	for (const m of block.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) out[m[1]] = m[2].toLowerCase();
	return out;
}

const dark = tokens(css.match(/:root\s*\{([^}]*)\}/)![1]);
const light = { ...dark, ...tokens(css.match(/\[data-theme='light'\]\s*\{([^}]*)\}/)![1]) };

function luminance(hex: string): number {
	const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
	const f = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
	return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function contrast(a: string, b: string): number {
	const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
}

const TEXT = ['text', 'text-muted', 'accent', 'up', 'down', 'success', 'warning', 'danger'];
const SURFACES = ['bg', 'surface', 'surface-hover'];
const ON_SOFT: Array<[string, string]> = [
	['success', 'success-soft'],
	['warning', 'warning-soft'],
	['danger', 'danger-soft'],
	['text', 'warning-soft'],
	['text-muted', 'success-soft'],
	['text-muted', 'warning-soft'],
	['text-muted', 'danger-soft']
];
const CONTROL_BORDERS: Array<[string, string]> = [
	['border-input', 'bg'],
	['border-input', 'surface']
];

describe.each([
	['dark', dark],
	['light', light]
] as const)('%s theme contrast (#24)', (_name, t) => {
	it('defines every token the pairs below need', () => {
		for (const k of [...TEXT, ...SURFACES, 'success-soft', 'warning-soft', 'danger-soft', 'border-input']) {
			expect(t[k], `--${k}`).toMatch(/^#[0-9a-f]{6}$/);
		}
	});

	it.each(TEXT.flatMap((fg) => SURFACES.map((bg) => [fg, bg])))(
		'text token %s on %s is at least 4.5:1',
		(fg, bg) => expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
	);

	it.each(ON_SOFT)('%s on %s is at least 4.5:1', (fg, bg) =>
		expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
	);

	it.each(CONTROL_BORDERS)('control border %s on %s is at least 3:1 (WCAG 1.4.11)', (fg, bg) =>
		expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(3)
	);
});

describe('contrast()', () => {
	it('matches the WCAG reference values', () => {
		expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 1);
		expect(contrast('#767676', '#ffffff')).toBeCloseTo(4.54, 2);
	});
});
