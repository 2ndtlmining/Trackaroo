import { describe, expect, it, vi } from 'vitest';
import { mount, unmount } from 'svelte';

// Filters reads the current URL from $app/state and navigates with $app/navigation.
// Neither exists outside a SvelteKit runtime, so both are stubbed here rather
// than file-wide in components.test.ts, where nothing else needs them.
vi.mock('$app/state', () => ({
	page: { url: new URL('http://localhost/products') }
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Filters } = await import('../src/lib/components/Filters.svelte');

function renderComponent(Component: unknown, props: Record<string, unknown> = {}): string {
	const target = document.createElement('div');
	const comp = mount(Component as never, { target, props });
	const html = target.innerHTML;
	unmount(comp);
	return html;
}

describe('Filters retailer chips', () => {
	const facets = [
		{ value: 'scorptec', label: 'Scorptec', count: 12 },
		{ value: 'pccg', label: 'PCCG', count: 7 }
	];
	const props = { brands: ['AMD'], retailerFacets: facets, retailerTotal: 19 };

	it('renders a retailer chip per option with its count', () => {
		const html = renderComponent(Filters, props);
		expect(html).toContain('Scorptec');
		expect(html).toContain('12');
		expect(html).toContain('PCCG');
		expect(html).toContain('7');
	});

	it('no longer renders a retailer select', () => {
		const html = renderComponent(Filters, props);
		expect(html).not.toContain('aria-label="Filter by retailer"');
	});

	it('keeps the other filter controls', () => {
		const html = renderComponent(Filters, props);
		expect(html).toContain('aria-label="Filter by category"');
		expect(html).toContain('aria-label="Filter by brand"');
		expect(html).toContain('aria-label="Filter by generation tier"');
		expect(html).toContain('aria-label="Search by model"');
	});

	it('hides the chip row when only one retailer has results', () => {
		const html = renderComponent(Filters, {
			brands: ['AMD'],
			retailerFacets: [facets[0]],
			retailerTotal: 12
		});
		expect(html).not.toContain('Retailer');
	});
});
