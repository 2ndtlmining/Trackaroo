import { expect, test, type Page } from '@playwright/test';
import Database from 'better-sqlite3';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getMatchup } from '../src/lib/server/queries/matchups';

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

const ROUTES = ['/', '/products?category=gpu', '/products?category=cpu', '/deals', '/movers', '/compare', '/product/1', '/value'];

const here = path.dirname(fileURLToPath(import.meta.url));
function matchupProductId(): number {
	const db = new Database(path.join(here, 'e2e.db'), { readonly: true });
	try {
		const ids = db
			.prepare("SELECT id FROM products WHERE category = 'gpu' AND tracked = 1 AND brand IN ('NVIDIA', 'AMD') ORDER BY id")
			.all() as { id: number }[];
		const hit = ids.find(({ id }) => getMatchup(db as any, id) !== null);
		if (!hit) throw new Error('seeded e2e.db has no product with a matchup');
		return hit.id;
	} finally {
		db.close();
	}
}

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

	test('filter dialog opens, focuses inside, applies, returns focus (#23)', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const open = page.getByRole('button', { name: /^Filters/ });
		await expect(open).toHaveText(/Filters \(0 active\)/);
		await open.click();
		const dialog = page.getByRole('dialog', { name: 'Filters' });
		await expect(dialog).toBeVisible();
		expect(await dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
		await dialog.getByRole('checkbox', { name: 'NVIDIA', exact: true }).check();
		await dialog.getByRole('button', { name: /^Show \d+ results?$/ }).click();
		await expect(dialog).toBeHidden();
		await expect(open).toBeFocused();
		await expect(page).toHaveURL(/brand=NVIDIA/);
		await expect(open).toHaveText(/Filters \(1 active\)/);
	});

	test('while searching, the panel counts the search results (#23)', async ({ page }) => {
		await goto(page, '/products?category=gpu&q=5060');
		const rows = await page.getByTestId('catalog-row').count();
		await page.getByRole('button', { name: /^Filters/ }).click();
		expect(rows).toBeGreaterThan(0);
		await expect(
			page.getByRole('dialog', { name: 'Filters' }).getByRole('button', { name: /^Show \d+ results?$/ })
		).toHaveAccessibleName(new RegExp(`^Show ${rows} results?$`));
	});

	// Final review #3: a modal dialog makes the rest of the page inert, and the
	// dialog itself is md:hidden, so widening past md with it open (a tablet
	// rotating) must close it rather than leave an inert, dialog-less page.
	test('widening past md closes the open filter dialog (#23)', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await page.getByRole('button', { name: /^Filters/ }).click();
		const dialog = page.getByRole('dialog', { name: 'Filters' });
		await expect(dialog).toBeVisible();
		await page.setViewportSize({ width: 1024, height: 844 });
		await expect
			.poll(() => page.locator('dialog[aria-label="Filters"]').evaluate((d) => (d as HTMLDialogElement).open))
			.toBe(false);
		const form = page.getByRole('form', { name: 'Catalogue filters' });
		await form.getByRole('checkbox', { name: 'AMD', exact: true }).click({ timeout: 2000 });
		await expect(page).toHaveURL(/brand=AMD/);
	});

	test('the open filter dialog does not scroll horizontally (#23)', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await page.getByRole('button', { name: /^Filters/ }).click();
		await expect(page.getByRole('dialog', { name: 'Filters' })).toBeVisible();
		const { viewport, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth).toBeLessThanOrEqual(viewport + 1);
		const box = await page.getByRole('dialog', { name: 'Filters' }).boundingBox();
		expect(box!.x).toBeGreaterThanOrEqual(0);
		expect(box!.x + box!.width).toBeLessThanOrEqual(PHONE.width);
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

test.describe('phone without JavaScript (#23)', () => {
	test.use({ viewport: PHONE, javaScriptEnabled: false });

	test('the filters show inline and the dialog opener hides', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await expect(page.getByRole('button', { name: /^Filters/ })).toBeHidden();
		const form = page.getByRole('form', { name: 'Catalogue filters' });
		await expect(form).toBeVisible();
		await expect(form.getByRole('button', { name: 'Apply filters' })).toBeVisible();
		const { viewport, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth).toBeLessThanOrEqual(viewport + 1);
	});
});

test.describe('very narrow viewport', () => {
	test.use({ viewport: NARROW });

	test('/value scales its scatter down to 320px (#33)', async ({ page }) => {
		for (const route of ['/value', '/value?category=cpu']) {
			await goto(page, route);
			const svg = page.locator('figure svg').first();
			const box = await svg.boundingBox();
			expect(box!.x).toBeGreaterThanOrEqual(0);
			expect(box!.x + box!.width).toBeLessThanOrEqual(NARROW.width);
			const { viewport, scrollWidth } = await horizontalOverflow(page);
			expect(scrollWidth, `${route} overflows at 320px`).toBeLessThanOrEqual(viewport + 1);
			// The table keeps every point reachable without the chart.
			await expect(page.getByTestId('value-table').locator('tbody tr')).toHaveCount(
				await page.getByTestId('value-point').count()
			);
		}
	});

	test('products index survives 320px', async ({ page }) => {
		await goto(page, '/products');
		const { viewport, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth).toBeLessThanOrEqual(viewport + 1);
	});
});

test.describe('discover mobile', () => {
	test.use({ viewport: PHONE });

	test('/discover fits a 390px screen without horizontal scroll', async ({ page }) => {
		await goto(page, '/discover');
		const { viewport, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth, '/discover overflows its viewport').toBeLessThanOrEqual(viewport + 1);
		await expect(page.getByTestId('discover-untracked').getByRole('button', { name: 'Track' }).first()).toBeVisible();
	});
});

test.describe('PageHeader with the longest product name (#22)', () => {
	test.use({ viewport: NARROW });

	test('the product page does not overflow at 320px', async ({ page }) => {
		const db = new Database(path.join(path.dirname(fileURLToPath(import.meta.url)), 'e2e.db'), {
			readonly: true
		});
		const row = db
			.prepare('SELECT id FROM products WHERE tracked = 1 ORDER BY length(model) DESC, id LIMIT 1')
			.get() as { id: number };
		db.close();
		await goto(page, `/product/${row.id}`);
		await expect(page.locator('h1')).toHaveCount(1);
		const { viewport, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth).toBeLessThanOrEqual(viewport + 1);
	});

	test('the product page with a head-to-head panel does not overflow at 320px (#60)', async ({ page }) => {
		await goto(page, `/product/${matchupProductId()}`);
		await expect(page.getByTestId('matchup')).toBeVisible();
		const { viewport, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth).toBeLessThanOrEqual(viewport + 1);
	});
});

// #22 R5: the phone header nav wraps to a second row instead of scrolling, so
// no link is cut mid-word and the Discover pending badge stays visible.
for (const viewport of [PHONE, NARROW]) {
	test(`every header nav link is fully on screen at ${viewport.width}px`, async ({ page }) => {
		await page.setViewportSize(viewport);
		await goto(page, '/');
		const links = page.getByRole('navigation', { name: 'Main' }).getByRole('link');
		const n = await links.count();
		expect(n).toBeGreaterThan(0);
		for (let i = 0; i < n; i++) {
			const box = await links.nth(i).boundingBox();
			expect(box, `nav link ${i} has a box`).not.toBeNull();
			expect(box!.x, `nav link ${i} starts off screen`).toBeGreaterThanOrEqual(0);
			expect(box!.x + box!.width, `nav link ${i} runs past the viewport`).toBeLessThanOrEqual(viewport.width);
		}
		const { viewport: vw, scrollWidth } = await horizontalOverflow(page);
		expect(scrollWidth).toBeLessThanOrEqual(vw + 1);
	});
}
