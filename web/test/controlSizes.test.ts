// #22 Task 5: controls are big enough to read and hit. Chips and buttons are
// at least 28 px tall (min-h-7), badges 24 px (min-h-6), and none of their
// text drops under 12 px (text-xs / text-meta is the floor).
import { describe, expect, it } from 'vitest';
import { mount, unmount } from 'svelte';
import fs from 'node:fs';
import path from 'node:path';
import Badge from '../src/lib/components/Badge.svelte';
import Chip from '../src/lib/components/Chip.svelte';
import SegmentedControl from '../src/lib/components/SegmentedControl.svelte';
import FacetChips from '../src/lib/components/FacetChips.svelte';

function render(Component: unknown, props: Record<string, unknown>): HTMLElement {
	const target = document.createElement('div');
	const comp = mount(Component as never, { target, props });
	const clone = target.cloneNode(true) as HTMLElement;
	unmount(comp);
	return clone;
}

// Any arbitrary size under 12 px (px, or rem below 0.75), or Tailwind's 2xs.
const TOO_SMALL = /\btext-(\[(?:(?:[0-9]|1[01])(?:\.\d+)?px|0?\.(?:[0-6]\d*|7(?:[0-4]\d*)?)rem)\]|2xs)(?![\w-])/;
const classesIn = (el: HTMLElement) =>
	[el, ...el.querySelectorAll<HTMLElement>('*')].map((e) => e.getAttribute('class') ?? '').join(' ');

describe('control sizes (#22 Task 5)', () => {
	it('Chip is at least 28 px tall with 12 px+ text', () => {
		const root = render(Chip, { label: 'Low', value: '$329' }).firstElementChild as HTMLElement;
		expect(root.classList.contains('min-h-7')).toBe(true);
		expect(classesIn(root)).not.toMatch(TOO_SMALL);
	});

	it('Badge is at least 24 px tall with 12 px+ text', () => {
		const root = render(Badge, { tone: 'up', label: 'Rising' }).firstElementChild as HTMLElement;
		expect(root.classList.contains('min-h-6')).toBe(true);
		expect(root.className).toMatch(/\btext-(xs|meta)\b/);
		expect(classesIn(root)).not.toMatch(TOO_SMALL);
	});

	it('SegmentedControl buttons are at least 28 px tall with 12 px+ text', () => {
		const root = render(SegmentedControl, {
			label: 'Window',
			options: [
				{ value: '7', label: '7d' },
				{ value: '30', label: '30d' }
			],
			value: '7',
			onChange: () => {}
		});
		const buttons = root.querySelectorAll('button');
		expect(buttons).toHaveLength(2);
		for (const b of buttons) {
			expect(b.classList.contains('min-h-7')).toBe(true);
			expect(b.className).not.toMatch(TOO_SMALL);
		}
	});
});

describe('control text floor across web/src (#22 Task 5, fix round 1)', () => {
	it('the size floor catches px and rem arbitrary sizes', () => {
		for (const bad of ['text-[10px]', 'text-[11.5px]', 'text-[0.65rem]', 'text-[.7rem]', 'text-2xs'])
			expect(bad).toMatch(TOO_SMALL);
		for (const ok of ['text-[12px]', 'text-[0.75rem]', 'text-[0.8rem]', 'text-xs', 'text-meta', 'text-[13px]'])
			expect(ok).not.toMatch(TOO_SMALL);
	});

	it('no <button> in web/src has text under 12 px anywhere inside it', () => {
		const SRC = path.resolve(__dirname, '..', 'src');
		const walk = (dir: string): string[] =>
			fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
				e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]
			);
		const offenders = walk(SRC)
			.filter((f) => f.endsWith('.svelte'))
			.flatMap((f) =>
				[...fs.readFileSync(f, 'utf-8').matchAll(/<button\b[\s\S]*?<\/button>/g)]
					.filter((m) => TOO_SMALL.test(m[0]))
					.map((m) => `${path.relative(SRC, f)}: ${m[0].match(TOO_SMALL)![0]}`)
			);
		expect(offenders).toEqual([]);
	});
});

describe('pressed chips differ by more than colour (WCAG 1.4.1, fix round 1)', () => {
	const SIZES = new Set(['xs', 'sm', 'base', 'body', 'meta', 'title', 'display', 'section', 'price']);
	// Drop colour-only classes; what is left is the non-colour styling.
	const nonColour = (cls: string) =>
		cls
			.split(/\s+/)
			.filter(Boolean)
			.filter((c) => !c.startsWith('hover:') && !/^(bg|border)-/.test(c))
			.filter((c) => !(c.startsWith('text-') && !SIZES.has(c.slice(5))))
			.sort()
			.join(' ');

	it('FacetChips: the active chip has a check mark and a heavier weight', () => {
		const root = render(FacetChips, {
			label: 'Retailer',
			options: [
				{ value: 'pccg', label: 'PCCG', count: 2 },
				{ value: 'scorptec', label: 'Scorptec', count: 3 }
			],
			selected: 'pccg',
			allCount: 5,
			onSelect: () => {}
		});
		const active = root.querySelector('button[aria-pressed="true"]') as HTMLElement;
		const inactive = root.querySelector('button[aria-pressed="false"]') as HTMLElement;
		expect(nonColour(active.className)).not.toBe(nonColour(inactive.className));
		expect(active.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
		expect(inactive.querySelector('svg')).toBeNull();
		expect(active.textContent?.trim()).toMatch(/^PCCG/);
	});
});
