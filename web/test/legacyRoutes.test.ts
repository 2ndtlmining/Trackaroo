import { describe, expect, it } from 'vitest';
import { categoryRedirect } from '../src/lib/legacyRoutes';

describe('categoryRedirect (U2)', () => {
	it('sends /gpus to the GPU index', () => {
		expect(categoryRedirect('gpu', new URLSearchParams())).toBe('/products?category=gpu');
	});

	it('keeps whatever the visitor searched for, category first', () => {
		expect(categoryRedirect('cpu', new URLSearchParams('q=9800x3d'))).toBe(
			'/products?category=cpu&q=9800x3d'
		);
	});

	it('the path wins over a conflicting category parameter', () => {
		expect(categoryRedirect('gpu', new URLSearchParams('category=cpu&q=x'))).toBe(
			'/products?category=gpu&q=x'
		);
	});
});
