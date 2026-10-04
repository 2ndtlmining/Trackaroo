import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import Database from 'better-sqlite3';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getMatchup } from '../src/lib/server/queries/matchups';

const here = path.dirname(fileURLToPath(import.meta.url));

async function goto(page: Page, path: string) {
	await page.goto(path);
	await page.waitForLoadState('networkidle');
}

// Rules disabled here need a written reason (spec section 7). Keep this list
// empty unless a violation is a false positive that cannot be fixed in markup.
const DISABLED_RULES: string[] = [];

function compareIds(): [number, number] {
	const db = new Database(path.join(here, 'e2e.db'), { readonly: true });
	const ids = db
		.prepare("SELECT product_id AS id FROM specs WHERE category = 'gpu' AND vram_gb IS NOT NULL ORDER BY vram_gb DESC")
		.all() as { id: number }[];
	db.close();
	expect(ids.length).toBeGreaterThanOrEqual(2);
	return [ids[0].id, ids[ids.length - 1].id];
}

// The product page with seeded OzBargain deals (#34), expired toggle included.
const OZB_PRODUCT = '/product/<E2E Deal Demo GPU>';
function ozbProductId(): number {
	const db = new Database(path.join(here, 'e2e.db'), { readonly: true });
	try {
		return (db.prepare("SELECT id FROM products WHERE model = 'E2E Deal Demo GPU'").get() as { id: number }).id;
	} finally {
		db.close();
	}
}

const MATCHUP_PRODUCT = '/product/<matchup>';
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

async function scan(page: Page, theme: 'light' | 'dark', route: string) {
	// The site themes via a stored preference, not prefers-color-scheme.
	await page.addInitScript((t) => localStorage.setItem('trackaroo-theme', t), theme);
	await goto(page, route);
	await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
	const results = await new AxeBuilder({ page }).disableRules(DISABLED_RULES).analyze();
	const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
	expect(bad.map((v) => `${v.id}: ${v.nodes.length} node(s) - ${v.help}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([]);
}

const PAGES = [
	'/',
	'/products?category=gpu',
	'/products?category=cpu',
	'/product/1',
	'/deals',
	'/movers',
	'/discover',
	'/changelog',
	'/compare',
	'/value',
	'/value?category=cpu',
	'/product/999999',
	OZB_PRODUCT,
	MATCHUP_PRODUCT
];

test('the two themes really render different backgrounds', async ({ browser }) => {
	const bgs: string[] = [];
	for (const theme of ['light', 'dark'] as const) {
		const ctx = await browser.newContext();
		const page = await ctx.newPage();
		await page.addInitScript((t) => localStorage.setItem('trackaroo-theme', t), theme);
		await goto(page, '/');
		bgs.push(await page.evaluate(() => getComputedStyle(document.body).backgroundColor));
		await ctx.close();
	}
	expect(bgs[0]).not.toBe(bgs[1]);
});

for (const theme of ['light', 'dark'] as const) {
	test.describe(`axe (${theme})`, () => {
		for (const route of PAGES) {
			test(`${route} has no serious or critical violations`, async ({ page }) => {
				// Seed ids are read here, not at module load: Playwright collects
				// tests before the webServer runs seed.mjs, so e2e.db may not exist yet.
				let target = route;
				if (route === '/compare') {
					const [a, b] = compareIds();
					target = `/compare?ids=${a},${b}`;
				}
				if (route === OZB_PRODUCT) target = `/product/${ozbProductId()}`;
				if (route === MATCHUP_PRODUCT) target = `/product/${matchupProductId()}`;
				await scan(page, theme, target);
			});
		}

		test.describe('phone', () => {
			test.use({ viewport: { width: 390, height: 844 } });
			test('/products?category=gpu at 390px, filter dialog closed', async ({ page }) => {
				await scan(page, theme, '/products?category=gpu');
			});
		});
	});
}
