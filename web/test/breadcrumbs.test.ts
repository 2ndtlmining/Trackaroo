import { describe, expect, it } from 'vitest';
import { productBreadcrumbs } from '../src/lib/breadcrumbs';

describe('productBreadcrumbs (#26)', () => {
	it('walks back to the category, then the brand and generation', () => {
		expect(
			productBreadcrumbs({
				category: 'gpu',
				brand: 'NVIDIA',
				model: 'GeForce RTX 5070 Ti',
				generation_tier: 'current'
			})
		).toEqual([
			{ label: 'GPUs', href: '/products?category=gpu' },
			{ label: 'NVIDIA RTX 50 (Blackwell)', href: '/products?category=gpu&q=NVIDIA' },
			{ label: 'GeForce RTX 5070 Ti', href: null }
		]);
	});

	it('falls back to the brand alone without a tier', () => {
		const crumbs = productBreadcrumbs({ category: 'cpu', brand: 'AMD', model: 'Ryzen 5 5600', generation_tier: null });
		expect(crumbs[0]).toEqual({ label: 'CPUs', href: '/products?category=cpu' });
		expect(crumbs[1].label).toBe('AMD');
	});
});
