import { describe, it, expect } from 'vitest';
import { NAV_LINKS, isActiveLink } from '../src/lib/nav';

const params = (s: string) => new URLSearchParams(s);

describe('NAV_LINKS', () => {
	it('puts Deals first — the site purpose gets the first slot', () => {
		expect(NAV_LINKS[0]).toEqual({ href: '/deals', label: 'Deals' });
	});

	it('replaces Products with GPUs and CPUs, and includes Compare', () => {
		expect(NAV_LINKS.map((l) => l.label)).toEqual(['Deals', 'GPUs', 'CPUs', 'Movers', 'Compare']);
	});
});

describe('isActiveLink', () => {
	it('matches a plain path', () => {
		expect(isActiveLink('/deals', '/deals', params(''))).toBe(true);
		expect(isActiveLink('/deals', '/movers', params(''))).toBe(false);
	});

	// The old check compared pathname to the whole href, so neither category
	// link could ever highlight.
	it('matches a category link on the query string', () => {
		expect(isActiveLink('/products?category=gpu', '/products', params('category=gpu'))).toBe(true);
		expect(isActiveLink('/products?category=cpu', '/products', params('category=gpu'))).toBe(false);
	});

	it('does not highlight a category link on an unfiltered /products', () => {
		expect(isActiveLink('/products?category=gpu', '/products', params(''))).toBe(false);
	});

	it('ignores unrelated query parameters', () => {
		expect(
			isActiveLink('/products?category=gpu', '/products', params('category=gpu&sort=price-asc'))
		).toBe(true);
		expect(isActiveLink('/movers', '/movers', params('window=30d'))).toBe(true);
	});
});

describe('isActiveLink on a product page (#26)', () => {
	it('highlights the product’s category and nothing else', () => {
		expect(isActiveLink('/products?category=gpu', '/product/12', params(''), 'gpu')).toBe(true);
		expect(isActiveLink('/products?category=cpu', '/product/12', params(''), 'gpu')).toBe(false);
		expect(isActiveLink('/deals', '/product/12', params(''), 'gpu')).toBe(false);
	});

	it('changes nothing elsewhere', () => {
		expect(isActiveLink('/products?category=gpu', '/products', params('category=gpu'), null)).toBe(true);
	});
});
