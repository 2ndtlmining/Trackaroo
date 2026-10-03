// #22 Task 5: controls are big enough to read and hit. Chips and buttons are
// at least 28 px tall (min-h-7), badges 24 px (min-h-6), and none of their
// text drops under 12 px (text-xs / text-meta is the floor).
import { describe, expect, it } from 'vitest';
import { mount, unmount } from 'svelte';
import Badge from '../src/lib/components/Badge.svelte';
import Chip from '../src/lib/components/Chip.svelte';
import SegmentedControl from '../src/lib/components/SegmentedControl.svelte';

function render(Component: unknown, props: Record<string, unknown>): HTMLElement {
	const target = document.createElement('div');
	const comp = mount(Component as never, { target, props });
	const clone = target.cloneNode(true) as HTMLElement;
	unmount(comp);
	return clone;
}

// Any arbitrary pixel size under 12, or Tailwind's 2xs.
const TOO_SMALL = /\btext-(\[(?:[0-9]|1[01])(?:\.\d+)?px\]|2xs)\b/;
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
