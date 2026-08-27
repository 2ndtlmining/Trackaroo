import { expect, test, type Page } from '@playwright/test';

/**
 * Mobile viewport regression tests.
 *
 * The layout already collapses correctly at phone widths (tables swap to card
 * lists behind `md:`), and these tests exist to keep it that way: a stray
 * fixed width or an unwrapped table is easy to add and invisible on a desktop
 * run. They assert two things that are cheap to check and expensive to notice
 * by eye:
 *
 *  1. No route scrolls horizontally — the classic mobile breakage.
 *  2. Interactive controls meet the WCAG 2.2 AA 24x24 minimum target size.
 *
 * Kept deliberately small so the suite stays fast (see CLAUDE.md).
 */

const PHONE = { width: 390, height: 844 };
const NARROW = { width: 320, height: 844 };

const ROUTES = ['/', '/products', '/deals', '/movers'];

async function goto(page: Page, path: string) {
	await page.goto(path);
	// Wait for Svelte to finish hydrating so click/select handlers are attached
	await page.waitForLoadState('networkidle');
}

/** Widest horizontal extent of the document, vs the viewport. */
async function horizontalOverflow(page: Page) {
	return page.evaluate(() => ({
		viewport: document.documentElement.clientWidth,
		scrollWidth: document.documentElement.scrollWidth
	}));
}

test.describe('mobile viewport', () => {
	test.use({ viewport: PHONE });

	for (const route of ROUTES) {
		test(`${route} does not scroll horizontally at 390px`, async ({ page }) => {
			await goto(page, route);
			const { viewport, scrollWidth } = await horizontalOverflow(page);
			// 1px of slack for sub-pixel rounding.
			expect(scrollWidth, `${route} overflows its viewport`).toBeLessThanOrEqual(viewport + 1);
		});
	}

	test('product detail does not scroll horizontally at 390px', async ({ page }) => {
		await goto(page, '/products');
		const href = await page.locator('a[href^="/product/"]').first().getAttribute('href');
		expect(href, 'seeded data should expose at least one product link').toBeTruthy();

		await goto(page, href!);
		const { viewport, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth).toBeLessThanOrEqual(viewport + 1);
	});

	test('compare checkbox is a tappable target, not a bare 13px box', async ({ page }) => {
		await goto(page, '/products');
		const checkbox = page.locator('input[type=checkbox][aria-label^="Compare"]').first();
		await expect(checkbox).toBeVisible();

		// The padded <label> wrapper is the real touch target.
		const label = page.locator('label:has(input[aria-label^="Compare"])').first();
		const box = await label.boundingBox();
		expect(box, 'compare checkbox should have a wrapping label').not.toBeNull();
		expect(box!.height, 'touch target below WCAG 2.2 AA minimum').toBeGreaterThanOrEqual(24);
		expect(box!.width, 'touch target below WCAG 2.2 AA minimum').toBeGreaterThanOrEqual(24);
	});

	test('tapping the padded label toggles compare selection', async ({ page }) => {
		await goto(page, '/products');
		const checkbox = page.locator('input[type=checkbox][aria-label^="Compare"]').first();
		await expect(checkbox).not.toBeChecked();

		// Click the label's padding, outside the 16px input itself — this is
		// the area a thumb actually lands on.
		const label = page.locator('label:has(input[aria-label^="Compare"])').first();
		const box = await label.boundingBox();
		await page.mouse.click(box!.x + 2, box!.y + box!.height / 2);

		await expect(checkbox).toBeChecked();
	});
});

test.describe('very narrow viewport', () => {
	test.use({ viewport: NARROW });

	test('products index survives 320px', async ({ page }) => {
		await goto(page, '/products');
		const { viewport, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth).toBeLessThanOrEqual(viewport + 1);
	});
});
