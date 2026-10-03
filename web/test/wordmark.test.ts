import { describe, expect, it } from 'vitest';
import { mount, unmount } from 'svelte';
import Wordmark from '../src/lib/components/Wordmark.svelte';

function render(props: Record<string, unknown> = {}): HTMLElement {
	const target = document.createElement('div');
	mount(Wordmark as never, { target, props });
	return target;
}

describe('Wordmark (#22)', () => {
	it('is a home link named "Trackaroo home"', () => {
		const a = render().querySelector('a')!;
		expect(a.getAttribute('href')).toBe('/');
		expect(a.getAttribute('aria-label')).toBe('Trackaroo home');
	});

	it('reads trackaroo_', () => {
		expect(render().querySelector('a')!.textContent?.trim()).toBe('trackaroo_');
	});

	it('colours the underscore with the accent and hides it from AT', () => {
		const span = render().querySelector('a span')!;
		expect(span.textContent).toBe('_');
		expect(span.classList.contains('text-accent')).toBe(true);
		expect(span.getAttribute('aria-hidden')).toBe('true');
	});

	it('uses mono 600, with a larger large size', () => {
		const a = render().querySelector('a')!;
		expect(a.className).toContain('font-mono');
		expect(a.className).toContain('font-semibold');
		expect(a.className).toContain('text-[18px]');
		expect(render({ size: 'large' }).querySelector('a')!.className).toContain('text-[28px]');
	});
});
