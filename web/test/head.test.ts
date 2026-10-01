import { describe, expect, it } from 'vitest';
import { SITE_NAME, pageTitle, productPageTitle } from '../src/lib/head';

describe('pageTitle (#25)', () => {
	it('suffixes the site name with a middle dot', () => {
		expect(pageTitle('Deals')).toBe('Deals · Trackaroo');
	});

	it('gives the homepage the full site title', () => {
		expect(pageTitle()).toBe('Trackaroo — AU CPU & GPU price tracker');
		expect(pageTitle('   ')).toBe('Trackaroo — AU CPU & GPU price tracker');
	});

	it('names the site constant once', () => {
		expect(SITE_NAME).toBe('Trackaroo');
	});
});

describe('productPageTitle (#25)', () => {
	it('leads with the model, today’s price and the retailer', () => {
		expect(productPageTitle('GeForce RTX 5070 Ti', 1699, 'Scorptec')).toBe(
			'GeForce RTX 5070 Ti — $1,699 at Scorptec · Trackaroo'
		);
	});

	it('falls back to the model alone when nothing is in stock', () => {
		expect(productPageTitle('Radeon RX 6600', null, null)).toBe('Radeon RX 6600 · Trackaroo');
	});
});
