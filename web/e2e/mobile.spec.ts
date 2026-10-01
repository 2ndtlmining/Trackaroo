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

const ROUTES = ['/', '/products?category=gpu', '/products?category=cpu', '/deals', '/movers', '/compare', '/product/1'];

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

function slug(route: string): string {
	return route.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'home';
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

	for (const theme of ['dark', 'light'] as const) {
		for (const route of ROUTES) {
			test(`${route} renders at 390px in the ${theme} theme (screenshot, U6)`, async ({ page }) => {
				await page.addInitScript((t) => localStorage.setItem('trackaroo-theme', t), theme);
				await goto(page, route);
				await expect(page.locator('h1').first()).toBeVisible();
				await page.screenshot({ path: `test-results/mobile/${slug(route)}-${theme}.png`, fullPage: true });
				const { viewport, scrollWidth } = await horizontalOverflow(page);
				expect(scrollWidth, `${route} overflows in ${theme}`).toBeLessThanOrEqual(viewport + 1);
			});
		}
	}

	test('movers keeps the change column on screen and its controls tappable', async ({ page }) => {
		await goto(page, '/movers?window=30d');
		const change = page.locator('tbody tr').first().locator('td').filter({ has: page.locator('span') }).last();
		const box = await change.boundingBox();
		expect(box, 'first mover row has a change cell').not.toBeNull();
		expect(box!.x + box!.width).toBeLessThanOrEqual(PHONE.width);
		for (const name of ['$ change', '% change', 'Up', 'By product']) {
			const b = await page.getByRole('button', { name, exact: true }).boundingBox();
			expect(b!.height, `${name} below the 24px target`).toBeGreaterThanOrEqual(24);
		}
	});

	test('the product page’s buy panel and where-to-buy table fit a phone', async ({ page }) => {
		await goto(page, '/product/1');
		const panel = page.getByRole('region', { name: 'Is now a good time to buy?' });
		await expect(panel).toBeVisible();
		const box = await panel.boundingBox();
		expect(box!.x + box!.width).toBeLessThanOrEqual(PHONE.width);
		await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible();
	});

	test('the catalog explains its checkboxes on a phone (U5)', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await expect(page.getByText('Tick a box to compare up to four.')).toBeVisible();
		await expect(page.getByTestId('catalog-header')).toBeHidden();
	});

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
