import { describe, expect, it } from 'vitest';
import { createRawSnippet, mount } from 'svelte';
import PageHeader from '../src/lib/components/PageHeader.svelte';

function render(props: Record<string, unknown> = {}): HTMLElement {
	const target = document.createElement('div');
	mount(PageHeader as never, { target, props: { title: 'Deals', ...props } });
	return target;
}

describe('PageHeader (#22)', () => {
	it('renders the title as the only h1, inside the header', () => {
		const t = render();
		const h1s = t.querySelectorAll('h1');
		expect(h1s).toHaveLength(1);
		expect(h1s[0].textContent).toBe('Deals');
		expect(t.querySelector('[data-testid="page-header"] h1')).not.toBeNull();
		expect(h1s[0].classList.contains('text-display')).toBe(true);
	});

	it('compact uses text-title', () => {
		const h1 = render({ compact: true }).querySelector('h1')!;
		expect(h1.classList.contains('text-title')).toBe(true);
		expect(h1.classList.contains('text-display')).toBe(false);
	});

	it('renders subtitle only when given', () => {
		expect(render().querySelector('p')).toBeNull();
		const p = render({ subtitle: 'Cheapest today' }).querySelector('p')!;
		expect(p.textContent).toBe('Cheapest today');
		expect(p.classList.contains('text-body')).toBe(true);
		expect(p.classList.contains('text-text-muted')).toBe(true);
	});

	it('renders crumbs through Breadcrumbs', () => {
		const t = render({
			crumbs: [
				{ label: 'GPUs', href: '/products?category=gpu' },
				{ label: 'Card', href: null }
			]
		});
		const nav = t.querySelector('nav[aria-label="Breadcrumb"]')!;
		expect(nav.textContent).toContain('GPUs');
		expect(nav.textContent).toContain('Card');
		expect(render().querySelector('nav')).toBeNull();
	});

	it('renders the actions snippet', () => {
		const actions = createRawSnippet(() => ({ render: () => '<button>Go</button>' }));
		expect(render({ actions }).querySelector('button')!.textContent).toBe('Go');
	});

	it('accepts a snippet subtitle, so counts keep their tabular spans', () => {
		const subtitle = createRawSnippet(() => ({
			render: () => '<span><span class="num">47</span> tracked</span>'
		}));
		const p = render({ subtitle }).querySelector('[data-testid="page-header"] p')!;
		expect(p.textContent).toBe('47 tracked');
		expect(p.querySelector('.num')!.textContent).toBe('47');
		expect(p.classList.contains('text-text-muted')).toBe(true);
	});

	it('renders the meta snippet inside the header, under the title (R3)', () => {
		const meta = createRawSnippet(() => ({ render: () => '<p data-testid="m">NVIDIA</p>' }));
		const t = render({ meta, subtitle: 'Sub' });
		const header = t.querySelector('[data-testid="page-header"]')!;
		const m = header.querySelector('[data-testid="m"]')!;
		expect(m.textContent).toBe('NVIDIA');
		// After the h1 in document order, still above the bottom rule.
		const h1 = header.querySelector('h1')!;
		expect(h1.compareDocumentPosition(m) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(render().querySelector('[data-testid="page-header-meta"]')).toBeNull();
	});

	it('closes with a bottom border and pb-4 mb-6', () => {
		const cls = render().querySelector('header')!.className;
		for (const c of ['border-b', 'pb-4', 'mb-6']) expect(cls).toContain(c);
	});
});
