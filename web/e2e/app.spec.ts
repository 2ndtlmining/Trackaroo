import { test, expect, type Page } from '@playwright/test';
import Database from 'better-sqlite3';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { saleEventsInRange } from '../src/lib/saleEvents';

const here = path.dirname(fileURLToPath(import.meta.url));

// Set when the DB was seeded from CI's synthetic snapshots (write-synthetic-data.mjs)
// rather than a real scrape (#13). Some assertions depend on retailer/price
// variety that only the real, much larger scrape history happens to produce.
// A DEDICATED flag, not derived from TRACKAROO_DATA_DIR: that var only says
// where the data lives and CI itself never sets it (write-synthetic-data.mjs
// writes straight into the default ../data), so gating on TRACKAROO_DATA_DIR
// would never trigger the skip in CI at all (fix round 1, C1). Set as a
// job-level env in .github/workflows/ci.yml so this test process (not just
// the webServer child) sees it.
const SYNTHETIC = process.env.TRACKAROO_SYNTHETIC === '1';

async function goto(page: Page, path: string) {
	await page.goto(path);
	// Wait for Svelte to finish hydrating so click/select handlers are attached
	await page.waitForLoadState('networkidle');
}

// Mirrors the server-side deal rule (products/+page.server.ts) against the
// seeded e2e.db so the assertion holds for both the real data/ directory and
// the synthetic fallback: the current cheapest in-stock price must be below
// the average of the per-day cheapest in-stock price over the trailing 30
// days, with at least 3 days of history.
function expectedDeals(): { dealIds: number[]; nonDealId: number | null } {
	const db = new Database(path.join(here, 'e2e.db'), { readonly: true });
	try {
		const rows = db
			.prepare(
				`WITH latest AS (
					SELECT s.*
					FROM price_snapshots s
					JOIN (
						SELECT retailer_listing_id, MAX(snapshot_date) AS max_date
						FROM price_snapshots
						GROUP BY retailer_listing_id
					) m ON m.retailer_listing_id = s.retailer_listing_id
					  AND m.max_date = s.snapshot_date
				),
				day_min AS (
					SELECT l.product_id, s.snapshot_date, MIN(s.price_aud) AS price
					FROM retailer_listings l
					JOIN price_snapshots s ON s.retailer_listing_id = l.id
					WHERE s.stock_status = 'in_stock'
					  AND lower(l.variant_name) NOT LIKE '%bundle%'
					  AND lower(l.variant_name) NOT LIKE '%combo%'
					  AND lower(l.listing_url) NOT LIKE '%bundle%'
					  AND lower(l.listing_url) NOT LIKE '%bdl-%'
					  AND s.snapshot_date >= date((SELECT MAX(snapshot_date) FROM price_snapshots), '-30 days')
					GROUP BY l.product_id, s.snapshot_date
				),
				stats AS (
					SELECT product_id, AVG(price) AS avg30, COUNT(*) AS points
					FROM day_min
					GROUP BY product_id
				),
				cheapest AS (
					SELECT l.product_id, MIN(lat.price_aud) AS price
					FROM retailer_listings l
					JOIN latest lat ON lat.retailer_listing_id = l.id
					WHERE l.status = 'active'
					  AND lower(l.variant_name) NOT LIKE '%bundle%'
					  AND lower(l.variant_name) NOT LIKE '%combo%'
					  AND lower(l.listing_url) NOT LIKE '%bundle%'
					  AND lower(l.listing_url) NOT LIKE '%bdl-%'
					  AND lat.stock_status = 'in_stock'
					GROUP BY l.product_id
				)
				SELECT c.product_id AS id
				FROM cheapest c
				JOIN stats s ON s.product_id = c.product_id
				WHERE s.points >= 3
				  AND c.price < s.avg30
				ORDER BY c.product_id`
			)
			.all() as Array<{ id: number }>;
		const dealIds = rows.map((r) => r.id);
		const inStockIds = (
			db
				.prepare(
					`WITH latest AS (
						SELECT s.*
						FROM price_snapshots s
						JOIN (
							SELECT retailer_listing_id, MAX(snapshot_date) AS max_date
							FROM price_snapshots
							GROUP BY retailer_listing_id
						) m ON m.retailer_listing_id = s.retailer_listing_id
						  AND m.max_date = s.snapshot_date
					)
					SELECT DISTINCT l.product_id AS id
					FROM retailer_listings l
					JOIN latest lat ON lat.retailer_listing_id = l.id
					WHERE l.status = 'active' AND lat.stock_status = 'in_stock'
					ORDER BY l.product_id`
				)
				.all() as Array<{ id: number }>
		).map((r) => r.id);
		const nonDealId = inStockIds.find((id) => !dealIds.includes(id)) ?? null;
		return { dealIds, nonDealId };
	} finally {
		db.close();
	}
}

test.describe('navigation & layout', () => {
	test('puts Deals first and reaches every page', async ({ page }) => {
		await goto(page, '/');
		const nav = page.getByRole('navigation', { name: 'Main' });
		await expect(nav.getByRole('link').first()).toHaveText('Deals');
		for (const label of ['Deals', 'GPUs', 'CPUs', 'Movers', 'Compare']) {
			await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible();
		}
		// Discover carries a pending-count badge in its accessible name.
		await expect(nav.getByRole('link', { name: /^Discover/ })).toBeVisible();
	});

	test('header links navigate between pages', async ({ page }) => {
		await goto(page, '/');
		const nav = page.getByRole('navigation', { name: 'Main' });

		await nav.getByRole('link', { name: 'GPUs', exact: true }).click();
		await expect(page).toHaveTitle('GPUs · Trackaroo');
		await expect(page).toHaveURL(/category=gpu/);

		await nav.getByRole('link', { name: 'Movers', exact: true }).click();
		await expect(page).toHaveTitle('Movers · Trackaroo');

		await nav.getByRole('link', { name: 'Deals', exact: true }).click();
		await expect(page).toHaveTitle('Deals · Trackaroo');
	});

	// The old check compared pathname to the whole href, so neither category
	// link could ever highlight.
	test('highlights the GPUs link on /products?category=gpu', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const nav = page.getByRole('navigation', { name: 'Main' });
		await expect(nav.getByRole('link', { name: 'GPUs', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
		await expect(nav.getByRole('link', { name: 'CPUs', exact: true })).not.toHaveAttribute(
			'aria-current',
			'page'
		);
	});

	test('/gpus and /cpus redirect to the category index (U2)', async ({ page }) => {
		const gpus = await page.request.get('/gpus?q=5060', { maxRedirects: 0 });
		expect(gpus.status()).toBe(301);
		expect(gpus.headers()['location']).toBe('/products?category=gpu&q=5060');
		const cpus = await page.request.get('/cpus', { maxRedirects: 0 });
		expect(cpus.status()).toBe(301);
		expect(cpus.headers()['location']).toBe('/products?category=cpu');

		await goto(page, '/gpus');
		await expect(page.getByRole('heading', { name: 'GPUs', level: 1 })).toBeVisible();
	});

	test('footer shows the product tagline on every page', async ({ page }) => {
		await goto(page, '/products');
		await expect(page.getByText('Trackaroo — AU CPU & GPU price tracker')).toBeVisible();
		await expect(page.getByText('Logos are trademarks of their respective owners')).toBeVisible();
	});

	// The dataset stats moved into the homepage health strip (spec §6).
	test('header no longer carries the dataset stats', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByTitle('Distinct days with a snapshot')).toHaveCount(0);
		await expect(page.getByTitle('SQLite database size')).toHaveCount(0);
		await expect(page.getByLabel('Data health')).toBeVisible();
	});

	test('serves exactly one title and one description on every route (#25)', async ({ page }) => {
		for (const path of [
			'/',
			'/deals',
			'/movers',
			'/products?category=gpu',
			'/products?category=cpu',
			'/compare',
			'/product/1',
			'/product/999999'
		]) {
			const html = await (await page.request.get(path)).text();
			// Only <head>: Sparkline SVGs on /movers carry their own <title> for
			// accessibility, so counting the whole document would over-count.
			const head = html.split('</head>')[0];
			expect(head.match(/<title>/g)?.length, path).toBe(1);
			expect(head.match(/<meta name="description"/g)?.length, path).toBe(1);
			expect(html, path).toContain('property="og:title"');
			expect(html, path).toContain('rel="manifest"');
		}
	});

	test('names the product, price and retailer in a product page title (#25)', async ({ page }) => {
		await goto(page, '/product/1');
		// Anchored to the real productPageTitle() format so a regression (e.g.
		// dropping the price/retailer clause) actually fails this test.
		await expect(page).toHaveTitle(/^.+ — \$[\d,.]+ at .+ · Trackaroo$/);
	});
});

test('the empty /compare page picks two products in place (#26)', async ({ page }) => {
	await goto(page, '/compare');
	await expect(page.getByText('Nothing selected to compare yet.')).toBeVisible();
	await expect(page.getByText(/tick the compare box on each card/)).toHaveCount(0);
	const selects = page.getByRole('combobox');
	await selects.nth(0).selectOption({ index: 1 });
	await selects.nth(1).selectOption({ index: 2 });
	await page.getByRole('button', { name: 'Compare', exact: true }).click();
	await page.waitForLoadState('networkidle');
	await expect(page).toHaveURL(/\/compare\?id=\d+&id=\d+$/);
	await expect(page.locator('thead th a')).toHaveCount(2);
	await expect(page.getByText(/^Best price — (Scorptec|PCCG|Umart)$/).first()).toBeVisible();
});

test('the picker asks again when the same product is chosen twice (Review Focus 3)', async ({ page }) => {
	await goto(page, '/compare');
	const selects = page.getByRole('combobox');
	await selects.nth(0).selectOption({ index: 1 });
	await selects.nth(1).selectOption({ index: 1 });
	await page.getByRole('button', { name: 'Compare', exact: true }).click();
	await page.waitForLoadState('networkidle');
	await expect(page.getByRole('alert')).toHaveText('Pick two different products to compare.');
});

test.describe('theme toggle', () => {
	test('toggles between dark and light and persists', async ({ page }) => {
		await page.addInitScript(() => localStorage.setItem('trackaroo-theme', 'dark'));
		await goto(page, '/');

		// Dark first (stored default)
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
		const toggle = page.getByRole('button', { name: 'Switch to light mode' });
		await expect(toggle).toBeVisible();

		await toggle.click();
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
		await expect(page.getByRole('button', { name: 'Switch to dark mode' })).toBeVisible();
	});

test('respects a stored light theme on load', async ({ page }) => {
		await page.addInitScript(() => localStorage.setItem('trackaroo-theme', 'light'));
		await goto(page, '/');
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
	});

	test('persists the chosen theme across a reload', async ({ page }) => {
		// No stored theme → app defaults to dark; addInitScript is NOT used here
		// because it runs on every navigation and would clobber the saved value.
		await goto(page, '/');
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
		await page.getByRole('button', { name: 'Switch to light mode' }).click();
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

		await page.reload();
		await page.waitForLoadState('networkidle');
		await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
	});

	test('native controls and browser chrome follow the theme (#25)', async ({ page }) => {
		await page.addInitScript(() => localStorage.setItem('trackaroo-theme', 'light'));
		await goto(page, '/');
		await expect(page.locator('html')).toHaveCSS('color-scheme', 'light');
		await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#f6f7f9');
		await page.getByRole('button', { name: 'Switch to dark mode' }).click();
		await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark');
		await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0f1117');
	});
});

test.describe('homepage dashboard', () => {
	test('shows a data-health strip naming each retailer and its age', async ({ page }) => {
		await goto(page, '/');
		const strip = page.getByLabel('Data health');
		await expect(strip).toBeVisible();
		await expect(strip.getByText('Scorptec')).toBeVisible();
		await expect(strip.getByText('PCCG')).toBeVisible();
		// e2e/seed.mjs declares MWave active with no rows: it must be listed, not hidden (R1).
		await expect(strip.getByText('MWave')).toBeVisible();
		await expect(strip.getByText('missing').first()).toBeVisible();
	});

	test('renders a GPU and a CPU section with links through to the category', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByRole('link', { name: 'All GPUs →' })).toHaveAttribute(
			'href',
			'/products?category=gpu'
		);
		await expect(page.getByRole('link', { name: 'All CPUs →' })).toHaveAttribute(
			'href',
			'/products?category=cpu'
		);
	});

	test('surfaces the seeded deal fixture in the GPU top-deals column', async ({ page }) => {
		await goto(page, '/');
		await expect(
			page
				.getByLabel('GPUs')
				.getByTestId('top-deals')
				.getByRole('link', { name: 'E2E Deal Demo GPU' })
		).toBeVisible();
	});

	// A deal and a mover are different questions (spec §5): the fixture is both
	// cheap versus its own average AND the biggest recent drop, so it must
	// legitimately appear in both columns rather than being deduplicated.
	test('lists the same product as a deal and as a drop, because they differ', async ({ page }) => {
		await goto(page, '/');
		const gpus = page.getByLabel('GPUs');
		await expect(
			gpus.getByTestId('top-deals').getByRole('link', { name: 'E2E Deal Demo GPU' })
		).toBeVisible();
		await expect(
			gpus.getByTestId('biggest-drops').getByRole('link', { name: 'E2E Deal Demo GPU' })
		).toBeVisible();
	});

	// The homepage movers used to be per listing, so a retailer stocking several
	// SKUs of one card filled all three slots with rows that read identically.
	// They are product-level now (D7), so each slot is a different product by
	// construction.
	test('never lists the same product twice in a mover column', async ({ page }) => {
		await goto(page, '/');
		for (const section of ['GPUs', 'CPUs']) {
			for (const column of ['biggest-drops', 'biggest-rises']) {
				const links = page.getByLabel(section).getByTestId(column).getByRole('link');
				const hrefs = await links.evaluateAll((els) =>
					els.map((el) => el.getAttribute('href'))
				);
				expect(new Set(hrefs).size).toBe(hrefs.length);
			}
		}
	});

	test('mover rows describe the product’s cheapest price, one row per product (D7)', async ({ page }) => {
		await goto(page, '/');
		const drops = page.getByLabel('GPUs').getByTestId('biggest-drops');
		await expect(drops.getByRole('link', { name: 'E2E Deal Demo GPU', exact: true })).toBeVisible();
		// −90%: 1000 -> 100 on the fixture's only listing, so product == listing here.
		await expect(drops).toContainText('90.0%');
	});

	// Thin history is never summarised (Review Focus 1): the fixture falls
	// 1000 -> 600 over its only 2 days, which is under MIN_HISTORY_POINTS, so it
	// must not headline "Biggest drops" as a -40% move.
	test('a product with under MIN_HISTORY_POINTS days is not a homepage mover', async ({ page }) => {
		await goto(page, '/');
		const gpus = page.getByLabel('GPUs');
		for (const column of ['biggest-drops', 'biggest-rises']) {
			await expect(
				gpus.getByTestId(column).getByRole('link', { name: 'E2E Thin History GPU', exact: true })
			).toHaveCount(0);
		}
		// The page did render its movers: the long-history fixture is there.
		await expect(
			gpus.getByTestId('biggest-drops').getByRole('link', { name: 'E2E Deal Demo GPU', exact: true })
		).toBeVisible();
	});

	test('no longer renders the filter-and-sort listing table', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByRole('table')).toHaveCount(0);
	});

	test('shows both mover columns for each category', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByLabel('GPUs').getByText('Biggest drops (7d)')).toBeVisible();
		await expect(page.getByLabel('GPUs').getByText('Biggest rises (7d)')).toBeVisible();
	});

	// #22 Task 5: an empty movers column is not rendered as a blank panel. The
	// synthetic seed (CI) has no CPU rise: its Ryzen 9 9900X is flat and the
	// other CPUs fall. A local data/ scrape has none either as of Oct 2026; if
	// a real CPU rise ever lands there, the invariant test below still holds.
	// The CPU section shows one muted line instead of the column.
	test('a movers column with no rows is replaced by one line (#22)', async ({ page }) => {
		await goto(page, '/');
		const cpus = page.getByLabel('CPUs');
		await expect(cpus.getByTestId('biggest-rises')).toHaveCount(0);
		await expect(cpus.getByText('No big price rises this week.')).toBeVisible();
		await expect(cpus.getByTestId('biggest-drops')).toBeVisible();
	});

	test('every rendered movers column has rows; every missing one says so (#22)', async ({ page }) => {
		await goto(page, '/');
		const lines = { 'biggest-drops': 'No big price drops this week.', 'biggest-rises': 'No big price rises this week.' };
		for (const section of ['GPUs', 'CPUs']) {
			for (const [column, line] of Object.entries(lines)) {
				const col = page.getByLabel(section).getByTestId(column);
				if ((await col.count()) > 0) {
					expect(await col.getByRole('link').count()).toBeGreaterThan(0);
					await expect(page.getByLabel(section).getByText(line)).toHaveCount(0);
				} else {
					await expect(page.getByLabel(section).getByText(line)).toBeVisible();
				}
			}
		}
	});
});

// Filters.svelte moved off the homepage with the listing table (spec §5) and is
// now used only by /products, so its coverage moves here rather than being lost.
test.describe('product index', () => {
	test('hides never-listed products until asked, and search still finds them (#23)', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await expect(page.getByRole('link', { name: 'E2E Deal Demo GPU 8GB' })).toHaveCount(0);

		// The label flips Show -> Hide, so locate by the part that stays put.
		const toggle = page.getByRole('button', { name: /^(Show|Hide) \d+ not currently sold$/ });
		await expect(toggle).toHaveText(/^Show /);
		await expect(toggle).toHaveAttribute('aria-pressed', 'false');
		await toggle.click();
		await expect(toggle).toHaveText(/^Hide /);
		await expect(toggle).toHaveAttribute('aria-pressed', 'true');
		await expect(page.getByRole('link', { name: 'E2E Deal Demo GPU 8GB' })).toBeVisible();
		await expect(page).toHaveURL(/unlisted=1/);

		// Back from a product page keeps it (the Task 7 replaceState lesson:
		// read from location, not the stale page.url).
		await page.getByRole('link', { name: 'E2E Deal Demo GPU 8GB' }).click();
		await expect(page).toHaveURL(/\/product\/\d+/);
		await page.goBack();
		await page.waitForLoadState('networkidle');
		await expect(page.getByRole('button', { name: /^Hide \d+ not currently sold$/ })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		await expect(page.getByRole('link', { name: 'E2E Deal Demo GPU 8GB' })).toBeVisible();

		await goto(page, '/products?category=gpu&q=E2E%20Deal%20Demo');
		await expect(page.getByRole('link', { name: 'E2E Deal Demo GPU 8GB' })).toBeVisible();
	});

	test('names the base card’s memory where a memory sibling exists (follow-up)', async ({ page }) => {
		await goto(page, '/products?category=gpu&q=E2E%20Deal%20Demo');
		await expect(page.getByRole('link', { name: 'E2E Deal Demo GPU 16GB', exact: true })).toBeVisible();
		await page.getByRole('link', { name: 'E2E Deal Demo GPU 16GB', exact: true }).click();
		await page.waitForLoadState('networkidle');
		await expect(page.getByRole('heading', { level: 1 })).toHaveText('E2E Deal Demo GPU 16GB');
		await expect(page).toHaveTitle(/^E2E Deal Demo GPU 16GB/);
		await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText('E2E Deal Demo GPU 16GB');
		// The meta line's "· 16GB" (Task 5) is dropped once the name says it.
		await expect(page.getByTestId('product-meta')).not.toContainText('16GB');
	});

	test('the catalog shows column labels, VRAM and group counts (#23, U5)', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const header = page.getByTestId('catalog-header');
		for (const col of ['Compare', 'Price', 'Model', 'VRAM', 'Released', 'Listings']) {
			await expect(header).toContainText(col);
		}
		await expect(page.getByText('16GB', { exact: true }).first()).toBeVisible();
		await expect(page.getByRole('heading', { level: 2 }).first()).toContainText(/\d+ models? · \d+ in stock/);
	});

	test('groups the catalogue by brand and generation when the box is empty', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await expect(page.getByRole('heading', { name: 'GPUs', level: 1 })).toBeVisible();
		// Generation headings come from the shared tier labels.
		await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible();
		expect(await page.getByRole('link', { name: /GeForce|Radeon|Arc/ }).count()).toBeGreaterThan(3);
	});

	test('typing narrows the list and reports the count', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await page.getByLabel(/^Search GPUs$/).fill('5060');
		await expect(page.getByTestId('index-count')).toContainText('match');
		expect(await page.getByRole('link', { name: /GeForce RTX 5060/ }).count()).toBeGreaterThan(0);
		// Headings are replaced by a flat ranked list while searching.
		await expect(page.getByRole('heading', { level: 2 })).toHaveCount(0);
	});

	test('Enter opens the top hit', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const box = page.getByLabel(/^Search GPUs$/);
		await box.fill('5060 ti');
		await box.press('Enter');
		await expect(page).toHaveURL(/\/product\/\d+/);
	});

	test('Escape clears the box and restores the groups', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const box = page.getByLabel(/^Search GPUs$/);
		await box.fill('5060');
		await expect(page.getByRole('heading', { level: 2 })).toHaveCount(0);
		await box.press('Escape');
		await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible();
	});

	test('says so plainly when nothing matches', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await page.getByLabel(/^Search GPUs$/).fill('nosuchcardxyz');
		await expect(page.getByText(/No GPUs match/)).toBeVisible();
	});

	test('the CPUs destination shows CPUs, not GPUs', async ({ page }) => {
		await goto(page, '/products?category=cpu');
		await expect(page.getByRole('heading', { name: 'CPUs', level: 1 })).toBeVisible();
		expect(await page.getByRole('link', { name: /Ryzen|Core/ }).count()).toBeGreaterThan(3);
	});

	test('compare still reaches /compare from the index', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const boxes = page.getByRole('checkbox', { name: /^Compare / });
		await boxes.nth(0).check();
		await boxes.nth(1).check();
		await page
			.getByRole('region', { name: 'Compare bar' })
			.getByRole('link', { name: /Compare \(2\)/ })
			.click();
		await expect(page).toHaveURL(/\/compare\?ids=\d+,\d+/);
	});

	test('search lives in the URL and survives Back (#26)', async ({ page }) => {
		await goto(page, '/products?category=gpu&q=5060');
		await expect(page.getByLabel(/^Search GPUs$/)).toHaveValue('5060');
		await expect(page.getByTestId('index-count')).toContainText('match');

		await page.getByLabel(/^Search GPUs$/).fill('5060 ti');
		await expect(page).toHaveURL(/q=5060\+ti/);
		await page.getByRole('link', { name: /^GeForce RTX 5060 Ti( 16GB)?$/ }).first().click();
		await expect(page).toHaveURL(/\/product\/\d+/);
		await page.goBack();
		await page.waitForLoadState('networkidle');
		await expect(page.getByLabel(/^Search GPUs$/)).toHaveValue('5060 ti');
	});

	// Back/Forward between two /products entries reuses the component. The URL
	// sync must not track page.url (replaceState reads it internally), or on
	// Back it writes the entry just left over the one landed on.
	test('Back and Forward between two /products entries keep each entry\'s search', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const box = page.getByLabel(/^Search (GPUs|CPUs)$/);
		await box.fill('5060');
		await expect(page).toHaveURL(/q=5060$/);

		// The CPUs nav link is a real navigation: a second /products history
		// entry. (The In stock toggle replaces its entry, final review #5.)
		await page
			.getByRole('navigation', { name: 'Main' })
			.getByRole('link', { name: 'CPUs', exact: true })
			.click();
		await expect(page).toHaveURL(/category=cpu/);
		await page.waitForLoadState('networkidle');
		await box.fill('ryzen');
		await expect(page).toHaveURL(/q=ryzen/);

		await page.goBack();
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveURL(/\/products\?category=gpu&q=5060$/);
		await expect(box).toHaveValue('5060');
		// Still this entry's URL once the sync effect has had its chance to run.
		await expect(page).toHaveURL(/\/products\?category=gpu&q=5060$/);

		await page.goForward();
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveURL(/category=cpu/);
		await expect(page).toHaveURL(/q=ryzen/);
		await expect(box).toHaveValue('ryzen');
	});

	test('a shared compare selection is restored, and one pick prompts for another (#26)', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const boxes = page.getByRole('checkbox', { name: /^Compare / });
		await boxes.nth(0).check();
		const bar = page.getByRole('region', { name: 'Compare bar' });
		await expect(bar).toContainText('Pick 1 more to compare');
		await boxes.nth(1).check();
		await expect(page).toHaveURL(/compare=\d+%2C\d+|compare=\d+,\d+/);

		await page.reload();
		await page.waitForLoadState('networkidle');
		await expect(page.getByRole('checkbox', { name: /^Compare /, checked: true })).toHaveCount(2);
	});
});

// The catalogue's filters and sort live in the URL (#23, spec §4). Prices are
// read from the rendered rows, so these hold for the real scrape and the
// synthetic fixture alike.
async function rowPrices(page: Page): Promise<(number | null)[]> {
	const texts = await page.getByTestId('row-price').allTextContents();
	return texts.map((t) => {
		const v = t.trim();
		return v.startsWith('$') ? Number(v.replace(/[$,]/g, '')) : null;
	});
}

async function rowNames(page: Page): Promise<string[]> {
	return page.getByTestId('catalog-row').getByRole('link').allTextContents();
}

test.describe('catalogue filters and sort (#23)', () => {
	test('max price preset filters rows and writes ?max=', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const preset = page.getByRole('button', { name: '$1,000', exact: true });
		await expect(preset).toHaveAttribute('aria-pressed', 'false');
		await preset.click();
		await expect(page).toHaveURL(/max=1000/);
		await expect(preset).toHaveAttribute('aria-pressed', 'true');
		const prices = await rowPrices(page);
		expect(prices.length).toBeGreaterThan(0);
		for (const p of prices) {
			expect(p).not.toBeNull();
			expect(p!).toBeLessThanOrEqual(1000);
		}
	});

	test('the max price box applies after a pause, not per keystroke', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		// Record every URL the page writes, so a per-keystroke max=8 / max=80
		// would show up even though the address bar settles on max=800.
		await page.evaluate(() => {
			const seen: string[] = [];
			(window as unknown as { __urls: string[] }).__urls = seen;
			const original = history.replaceState.bind(history);
			history.replaceState = (data, unused, url) => {
				if (url) seen.push(String(url));
				return original(data, unused, url);
			};
		});
		await page.getByRole('spinbutton', { name: 'Max price' }).pressSequentially('800', { delay: 50 });
		await expect(page).toHaveURL(/max=800/);
		const urls = await page.evaluate(() => (window as unknown as { __urls: string[] }).__urls);
		expect(urls.some((u) => /max=800\b/.test(u))).toBe(true);
		expect(urls.filter((u) => /max=(8|80)(&|$)/.test(u))).toEqual([]);
		for (const p of await rowPrices(page)) expect(p!).toBeLessThanOrEqual(800);
	});

	test('a retailer that is no longer tracked still shows in the picker', async ({ page }) => {
		await goto(page, '/products?category=gpu&retailer=mwave');
		const select = page.getByRole('combobox', { name: 'Retailer' });
		await expect(select).toHaveValue('mwave');
		await expect(select.getByRole('option', { name: 'MWave (no longer tracked)' })).toHaveCount(1);
	});

	test('default order keeps series groups headed by their release year', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await expect(page.getByRole('heading', { level: 2 }).first()).toHaveText(/· \d{4}/);
	});

	test('brand + gen + retailer combine and survive reload', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await page.getByRole('checkbox', { name: 'NVIDIA', exact: true }).check();
		const gens = page.getByRole('group', { name: 'Generation' }).getByRole('checkbox');
		const genLabel = ((await gens.first().locator('xpath=..').textContent()) ?? '').trim();
		await gens.first().check();
		await page.getByRole('combobox', { name: 'Retailer' }).selectOption('scorptec');
		await expect(page).toHaveURL(/brand=NVIDIA/);
		await expect(page).toHaveURL(/gen=current/);
		await expect(page).toHaveURL(/retailer=scorptec/);
		await expect(page.getByRole('columnheader', { name: /Price at Scorptec/ })).toBeVisible();
		const before = await rowNames(page);

		await page.reload();
		await page.waitForLoadState('networkidle');
		await expect(page.getByRole('checkbox', { name: 'NVIDIA', exact: true })).toBeChecked();
		await expect(page.getByRole('checkbox', { name: 'AMD', exact: true })).not.toBeChecked();
		await expect(
			page.getByRole('group', { name: 'Generation' }).getByRole('checkbox', { name: genLabel, exact: true })
		).toBeChecked();
		await expect(page.getByRole('combobox', { name: 'Retailer' })).toHaveValue('scorptec');
		expect(await rowNames(page)).toEqual(before);
	});

	test('sort by price toggles direction and aria-sort', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const header = page.getByRole('columnheader', { name: /^Price/ });
		await expect(header).toHaveAttribute('aria-sort', 'none');
		await header.getByRole('button').click();
		await expect(page).toHaveURL(/sort=price/);
		await expect(header).toHaveAttribute('aria-sort', 'ascending');
		await expect(page.getByRole('columnheader', { name: /^Model/ })).toHaveAttribute('aria-sort', 'none');
		// Any sort flattens the series groups.
		await expect(page.getByRole('heading', { level: 2 })).toHaveCount(0);
		const asc = (await rowPrices(page)).filter((p): p is number => p !== null);
		expect(asc.length).toBeGreaterThan(1);
		expect(asc).toEqual([...asc].sort((a, b) => a - b));

		await header.getByRole('button').click();
		await expect(page).toHaveURL(/dir=desc/);
		await expect(header).toHaveAttribute('aria-sort', 'descending');
		const desc = (await rowPrices(page)).filter((p): p is number => p !== null);
		expect(desc).toEqual([...desc].sort((a, b) => b - a));
	});

	test('invalid params render the default view', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const plain = await page.getByTestId('catalog-row').count();
		await goto(page, '/products?category=gpu&max=abc&sort=bogus');
		await expect(page.getByTestId('catalog-row')).toHaveCount(plain);
		await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible();
	});

	test('no hydration errors on a filtered URL', async ({ page }) => {
		const errors: string[] = [];
		page.on('console', (msg) => {
			if (msg.type() === 'error' || msg.type() === 'warning') errors.push(msg.text());
		});
		page.on('pageerror', (err) => errors.push(err.message));
		await goto(page, '/products?category=gpu&brand=AMD&sort=price');
		await expect(page.getByRole('columnheader', { name: /^Price/ })).toHaveAttribute('aria-sort', 'ascending');
		expect(errors.filter((e) => /hydrat/i.test(e))).toEqual([]);
	});

	test('empty state', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const plain = await page.getByTestId('catalog-row').count();
		await goto(page, '/products?category=gpu&max=1');
		await expect(page.getByText('No products match these filters.')).toBeVisible();
		await expect(page.getByTestId('catalog-row')).toHaveCount(0);
		await page.getByTestId('catalog-empty').getByRole('link', { name: 'Clear filters' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page).not.toHaveURL(/max=/);
		await expect(page.getByTestId('catalog-row')).toHaveCount(plain);
	});

	test('CPU columns', async ({ page }) => {
		await goto(page, '/products?category=cpu');
		for (const name of ['Socket', 'Threads', 'Cores']) {
			await expect(page.getByRole('columnheader', { name: new RegExp(`^${name}`) })).toBeVisible();
		}
		await expect(page.getByRole('columnheader', { name: /^VRAM/ })).toHaveCount(0);
	});

	// Final review #1: a retailer view with in_stock off shows that retailer's
	// any-stock price, so a row whose only listings there are out of stock
	// must say so and must not show a deal cue. Read lazily from the seeded DB:
	// the synthetic fixture has no such product, so it skips there.
	test('a retailer view marks an out-of-stock price and drops its delta', async ({ page }) => {
		const db = new Database(path.join(here, 'e2e.db'), { readonly: true });
		let hit: { id: number; category: string; retailer: string } | undefined;
		try {
			hit = db
				.prepare(
					`WITH latest AS (
						SELECT s.* FROM price_snapshots s
						JOIN (
							SELECT retailer_listing_id, MAX(snapshot_date) AS max_date
							FROM price_snapshots
							GROUP BY retailer_listing_id
						) m ON m.retailer_listing_id = s.retailer_listing_id
						  AND m.max_date = s.snapshot_date
					)
					SELECT p.id, p.category, l.retailer
					FROM retailer_listings l
					JOIN latest lat ON lat.retailer_listing_id = l.id
					JOIN products p ON p.id = l.product_id
					WHERE l.status = 'active' AND p.tracked = 1
					  AND l.retailer IN ('scorptec', 'pccg', 'umart')
					  AND lower(l.variant_name) NOT LIKE '%bundle%'
					  AND lower(l.variant_name) NOT LIKE '%combo%'
					  AND lower(l.listing_url) NOT LIKE '%bundle%'
					  AND lower(l.listing_url) NOT LIKE '%bdl-%'
					GROUP BY p.id, l.retailer
					HAVING SUM(lat.stock_status = 'in_stock') = 0
					ORDER BY p.id, l.retailer
					LIMIT 1`
				)
				.get() as typeof hit;
		} finally {
			db.close();
		}
		test.skip(!hit, 'the seed has no product listed only out of stock at a retailer');
		await goto(page, `/products?category=${hit!.category}&retailer=${hit!.retailer}`);
		const row = page
			.getByTestId('catalog-row')
			.filter({ has: page.locator(`a[href="/product/${hit!.id}"]`) });
		await expect(row).toHaveCount(1);
		await expect(row.getByTestId('row-price')).toContainText('(out of stock)');
		await expect(row.getByTestId('row-delta')).toHaveText('No stock');
	});

	// Final review #2: the view applies to search results too. "x" matches
	// every GeForce RTX and Radeon RX model.
	test('a brand filter narrows the search results', async ({ page }) => {
		await goto(page, '/products?category=gpu&q=x');
		const all = await rowNames(page);
		expect(all.some((n) => /GeForce/.test(n))).toBe(true);
		expect(all.some((n) => /Radeon/.test(n))).toBe(true);
		await goto(page, '/products?category=gpu&brand=AMD&q=x');
		const amd = await rowNames(page);
		expect(amd.length).toBeGreaterThan(0);
		for (const n of amd) expect(n).toMatch(/Radeon/);
		await expect(page.getByTestId('index-count')).toContainText(`${amd.length} of`);
	});

	// Final review #5: the In stock toggle replaces the history entry, like
	// every other filter.
	test('the In stock toggle adds no history entry', async ({ page }) => {
		await goto(page, '/');
		await goto(page, '/products?category=gpu');
		await page.getByRole('checkbox', { name: 'In stock' }).check();
		await expect(page).toHaveURL(/in_stock=1/);
		await page.waitForLoadState('networkidle');
		await page.goBack();
		await page.waitForLoadState('networkidle');
		await expect(page).not.toHaveURL(/\/products/);
	});

	// Final review #6: an active filter keeps its control even when no row
	// has that value (no CPU is an NVIDIA one, in either seed).
	test('a selected brand no row has keeps a checked control', async ({ page }) => {
		await goto(page, '/products?category=cpu&in_stock=1&brand=NVIDIA');
		const box = page.getByRole('checkbox', { name: 'NVIDIA', exact: true });
		await expect(box).toBeChecked();
		// Unticking clears the filter; with no NVIDIA row the control then goes.
		await box.click();
		await expect(page).not.toHaveURL(/brand=/);
		await expect(box).toHaveCount(0);
		await expect(page.getByTestId('catalog-row').first()).toBeVisible();
	});

	test('each row has a 30-day trend with an accessible label', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const labels = await page
			.getByTestId('row-trend')
			.locator('[aria-label]')
			.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')));
		expect(labels.length).toBeGreaterThan(0);
		for (const l of labels) expect(l).toMatch(/^(30-day trend: (up|down) \d+%|30-day trend: flat|Not enough history)$/);
	});
});

test.describe('catalogue without JavaScript (#23)', () => {
	test.use({ javaScriptEnabled: false });

	test('shared link renders without JS', async ({ page }) => {
		await goto(page, '/products?category=gpu&max=500&sort=price');
		const prices = await rowPrices(page);
		expect(prices.length).toBeGreaterThan(0);
		for (const p of prices) expect(p!).toBeLessThanOrEqual(500);
		expect(prices).toEqual([...prices].sort((a, b) => a! - b!));
		await expect(page.getByRole('columnheader', { name: /^Price/ })).toHaveAttribute('aria-sort', 'ascending');
		// The controls are a plain GET form with a visible submit button.
		await expect(page.getByRole('button', { name: 'Apply filters' })).toBeVisible();
	});

	test('the filter form submits as a plain GET form', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const form = page.getByRole('form', { name: 'Catalogue filters' });
		await form.getByRole('checkbox', { name: 'NVIDIA', exact: true }).check();
		await form.getByRole('button', { name: 'Apply filters' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveURL(/brand=NVIDIA/);
		await expect(page.getByRole('checkbox', { name: 'NVIDIA', exact: true })).toBeChecked();
	});
});

test('the footer names the running build (#3)', async ({ page }) => {
	await goto(page, '/');
	// vite dev has no TRACKAROO_VERSION, so the stamp reads "dev".
	await expect(page.getByTestId('build-version')).toHaveText('build dev');
});

test('the footer release links to the changelog, which lists it first', async ({ page }) => {
	const pkg = JSON.parse(readFileSync(path.join(here, '..', 'package.json'), 'utf8'));
	await goto(page, '/');
	const release = page.getByTestId('release-version');
	await expect(release).toHaveText(`v${pkg.version}`);
	await expect(page.getByTestId('version-line')).toHaveText(`v${pkg.version} · build dev`);
	await release.click();
	await expect(page).toHaveURL(/\/changelog$/);
	await expect(page.getByRole('heading', { level: 1, name: "What's new" })).toBeVisible();
	await expect(page.getByTestId('release').first().getByRole('heading', { level: 2 })).toHaveText(
		`v${pkg.version}`
	);
	// Issue references become links to GitHub.
	await expect(page.getByRole('link', { name: '#16' })).toHaveAttribute(
		'href',
		'https://github.com/2ndtlmining/Trackaroo/issues/16'
	);
});

test('error page is styled and offers retry (#29)', async ({ page }) => {
	await goto(page, '/product/999999');
	await expect(page.getByRole('heading', { level: 1 })).toHaveText('Page not found');
	await expect(page.getByText('404', { exact: true })).toBeVisible();
	const retry = page.getByRole('link', { name: 'Try again' });
	await expect(retry).toHaveAttribute('href', '/product/999999');
	await expect(page.getByRole('main').getByRole('link', { name: 'Home', exact: true })).toHaveAttribute('href', '/');
});

test.describe('command palette', () => {
	test('is a combobox: active option, Enter, Escape returns focus, Tab is trapped (#29)', async ({ page }) => {
		await goto(page, '/');
		const trigger = page.getByRole('button', { name: 'Search products' });
		await trigger.focus();
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		const input = dialog.getByRole('combobox', { name: 'Search products' });
		await expect(input).toHaveAttribute('aria-expanded', 'true');
		await expect(input).toHaveAttribute('aria-autocomplete', 'list');
		const listboxId = await input.getAttribute('aria-controls');
		expect(listboxId).toBeTruthy();
		await expect(page.locator(`#${listboxId}`)).toHaveAttribute('role', 'listbox');

		await input.fill('rx 7800 xt');
		await page.keyboard.press('ArrowDown');
		const activeId = await input.getAttribute('aria-activedescendant');
		expect(activeId).toBeTruthy();
		const active = page.locator(`#${activeId}`);
		await expect(active).toHaveAttribute('role', 'option');
		await expect(active).toHaveAttribute('aria-selected', 'true');

		// Tab never leaves the palette.
		for (let i = 0; i < 4; i++) {
			await page.keyboard.press('Tab');
			expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
		}
		await page.keyboard.press('Shift+Tab');
		expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);

		await input.focus();
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL(/\/product\/\d+$/);

		// Reopen from the button, Escape closes and hands focus back to it.
		await trigger.focus();
		await page.keyboard.press('Control+k');
		await expect(dialog).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(dialog).toHaveCount(0);
		await expect(trigger).toBeFocused();
	});

	test('palette with no results has no active option and is not expanded', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const input = page.getByRole('combobox', { name: 'Search products' });
		await input.fill('zzzzzzzz-no-such-thing');
		await expect(input).not.toHaveAttribute('aria-activedescendant', /.+/);
		await expect(input).toHaveAttribute('aria-expanded', 'false');
	});

	test('opens with Ctrl+K, searches and navigates to a product on Enter', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await expect(dialog).toBeVisible();
		await expect(dialog.getByRole('combobox', { name: 'Search products' })).toBeFocused();

		// Exactly one match: two would render the palette's "Compare A vs B"
		// row instead, and Enter would open /compare.
		await dialog.getByRole('combobox', { name: 'Search products' }).fill('rx 7800 xt');
		const first = dialog.getByRole('option').first();
		await expect(first).toContainText('Radeon RX 7800 XT');
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL(/\/product\/\d+$/);
		await expect(page.getByRole('heading', { name: /Radeon RX 7800 XT/ })).toBeVisible();
	});

	test('closes with Escape', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await expect(dialog).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(dialog).toHaveCount(0);
	});

	test('offers a quick compare row when exactly two products match', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await expect(dialog).toBeVisible();
		await dialog.getByRole('combobox', { name: 'Search products' }).fill('RTX 5060');
		await expect(dialog.getByRole('option').first()).toContainText('Compare');
	});

	test('shows a snapshot count badge on each result', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await dialog.getByRole('combobox', { name: 'Search products' }).fill('RTX 5060');
		await expect(dialog.getByText(/snapshots/).first()).toBeVisible();
		await expect(dialog.getByText(/snapshots/)).toHaveCount(2);
	});

	test('uses the display name, so the base card shows its memory (follow-up)', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await dialog.getByRole('combobox', { name: 'Search products' }).fill('e2e deal demo gpu 16gb');
		await expect(dialog.getByRole('option').first()).toContainText('E2E Deal Demo GPU 16GB');
	});

	test('never offers a quick compare across categories (#26)', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		// "7600" matches the Ryzen 5 7600 CPU and (in real data) the RX 7600 GPU;
		// with synthetic data it matches one product. Either way, no compare row.
		await dialog.getByRole('combobox', { name: 'Search products' }).fill('7600');
		await expect(dialog.getByRole('option', { name: /^Compare / })).toHaveCount(0);
	});
});

test.describe('compare', () => {
	test('selecting two products enables the compare bar and opens /compare', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const boxes = page.getByRole('checkbox', { name: /^Compare / });
		await boxes.nth(0).check();
		await boxes.nth(1).check();

		const bar = page.getByRole('region', { name: 'Compare bar' });
		await expect(bar).toBeVisible();
		await bar.getByRole('link', { name: /Compare \(2\)/ }).click();

		await expect(page).toHaveURL(/\/compare\?ids=\d+,\d+$/);
		await expect(page.getByRole('heading', { name: 'Compare' })).toBeVisible();
		await expect(page.locator('thead th a')).toHaveCount(2);
		await expect(page.locator('thead svg[aria-label]')).toHaveCount(2);
		await expect(page.getByText('Architecture', { exact: true })).toBeVisible();
	});

	// The index is one category per page, so a mixed-category selection is no
	// longer reachable by clicking. Switching category must drop the selection,
	// or the compare link would carry GPUs into the CPU page and 400.
	test('switching category clears the selection', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const boxes = page.getByRole('checkbox', { name: /^Compare / });
		await boxes.nth(0).check();
		await boxes.nth(1).check();
		await expect(page.getByRole('region', { name: 'Compare bar' })).toBeVisible();

		await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'CPUs', exact: true }).click();
		await expect(page).toHaveURL(/category=cpu/);
		await expect(page.getByRole('region', { name: 'Compare bar' })).toHaveCount(0);
	});

	test('caps the selection at four', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const boxes = page.getByRole('checkbox', { name: /^Compare / });
		for (let i = 0; i < 4; i += 1) await boxes.nth(i).check();
		await expect(boxes.nth(4)).toBeDisabled();
	});

	test('clears the selection from the compare bar', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const boxes = page.getByRole('checkbox', { name: /^Compare / });
		await boxes.nth(0).check();
		await boxes.nth(1).check();

		const bar = page.getByRole('region', { name: 'Compare bar' });
		await bar.getByRole('button', { name: 'Clear' }).click();
		await expect(page.getByRole('region', { name: 'Compare bar' })).toHaveCount(0);
	});

	test('marks the best value in a spec row (#26)', async ({ page }) => {
		const db = new Database(path.join(here, 'e2e.db'), { readonly: true });
		const ids = db
			.prepare(
				"SELECT product_id AS id FROM specs WHERE category = 'gpu' AND vram_gb IS NOT NULL ORDER BY vram_gb DESC"
			)
			.all() as { id: number }[];
		db.close();
		expect(ids.length).toBeGreaterThanOrEqual(2);
		const [high, low] = [ids[0].id, ids[ids.length - 1].id];

		await goto(page, `/compare?ids=${low},${high}`);
		const cells = page.locator('tbody tr', { has: page.getByRole('rowheader', { name: 'VRAM', exact: true }) }).locator('td');
		await expect(cells).toHaveCount(2);
		await expect(cells.nth(0)).not.toContainText('Best');
		await expect(cells.nth(1)).toContainText('Best');
		await expect(cells.nth(1)).toContainText('16GB');
	});

	test('rejects invalid compare URLs', async ({ page }) => {
		expect((await page.request.get('/compare?ids=1')).status()).toBe(400);
		expect((await page.request.get('/compare?ids=1,2,3,4,5')).status()).toBe(400);
		expect((await page.request.get('/compare?ids=1,999999')).status()).toBe(404);
	});
});

test.describe('movers page', () => {
	test('renders movers with window buttons', async ({ page }) => {
		await goto(page, '/movers');
		await expect(page.getByRole('heading', { name: 'Movers' })).toBeVisible();
		for (const w of ['24h', '7d', '30d']) {
			await expect(page.getByRole('button', { name: w })).toBeVisible();
		}
await expect(page.locator('table')).toBeVisible();
		await expect(page.locator('table thead th').filter({ hasText: 'Trend' })).toBeVisible();
		await expect(page.locator('table svg polyline').first()).toBeVisible();
	});

	test('switching the window updates the URL and keeps data', async ({ page }) => {
		await goto(page, '/movers');
		await page.getByRole('button', { name: '24h' }).click();
		await expect(page).toHaveURL(/\/movers\?window=24h/);
		await expect(page.locator('table')).toBeVisible();

		await page.getByRole('button', { name: '30d' }).click();
		await expect(page).toHaveURL(/\/movers\?window=30d/);
	});

	test('invalid window falls back to the default', async ({ page }) => {
		await goto(page, '/movers?window=bogus');
		await expect(page.getByRole('heading', { name: 'Movers' })).toBeVisible();
		// Server defaults to 7d-tab highlighted
		await expect(page.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
	});

test('movers link through to product pages', async ({ page }) => {
		await goto(page, '/movers');
		const firstLink = page.locator('tbody tr a').first();
		await expect(firstLink).toBeVisible();
		const href = await firstLink.getAttribute('href');
		await expect(href).toMatch(/^\/product\/\d+$/);
		const id = href!.match(/\d+/)![0];

		await firstLink.click();
		await expect(page).toHaveURL(new RegExp(`/product/${id}$`));
	});

	test('column headers sort the movers table via the tri-state cycle', async ({ page }) => {
		await goto(page, '/movers');
		const newHeader = page.getByRole('button', { name: /^New/ });
		await expect(newHeader).toBeVisible();
		await newHeader.click();
		await expect(newHeader).toContainText('▲');
		await newHeader.click();
		await expect(newHeader).toContainText('▼');
		await newHeader.click();
		await expect(newHeader).not.toContainText('▲');
		await expect(newHeader).not.toContainText('▼');
	});

	// #5 items 1-3, 6: no "++$" double sign, no raw retailer slugs, thin/unchanged
	// listings hidden by default and demoted behind a click when shown.
	test('shows real movers first, correctly labelled, without the double plus', async ({ page }) => {
		const html = await (await page.request.get('/movers')).text();
		expect(html).not.toContain('++$');
		expect(html).not.toMatch(/>\s*(pccg|scorptec|umart)\s*</);

		await goto(page, '/movers');
		const first = page.locator('tbody tr').first();
		await expect(first).not.toContainText('Not enough history');

		await goto(page, '/movers?all=1');
		await expect(page.getByText('Not enough history').first()).toBeVisible();
	});

	test('groups listings under their product by default, and can list every SKU (#5 item 4)', async ({ page }) => {
		await goto(page, '/movers?window=30d&all=1');
		const leadHrefs = await page
			.locator('tbody > tr:first-child a[href^="/product/"]')
			.evaluateAll((els) => els.map((e) => e.getAttribute('href')));
		expect(new Set(leadHrefs).size).toBe(leadHrefs.length);

		// The RTX 5060 Ti has many listings in both seeds; its "+N more" expands in
		// place and relabels itself "Hide listings" (so re-query by the new name).
		const rowsBefore = await page.locator('tbody tr').count();
		await page.getByRole('button', { name: /^\+\d+ more listings?$/ }).first().click();
		await expect(page.getByRole('button', { name: /^Hide listings?$/ }).first()).toHaveAttribute(
			'aria-expanded',
			'true'
		);
		expect(await page.locator('tbody tr').count()).toBeGreaterThan(rowsBefore);

		await page.getByRole('button', { name: 'Per listing' }).click();
		await expect(page).toHaveURL(/group=0/);
		await expect(page.getByRole('button', { name: /(more|Hide) listings?$/ })).toHaveCount(0);
	});

	test('sort, direction and grouping live in the URL (#26)', async ({ page }) => {
		await goto(page, '/movers?window=30d&sort=pct&dir=down');
		await expect(page.getByRole('button', { name: '% change' })).toHaveAttribute('aria-pressed', 'true');
		await expect(page.getByRole('button', { name: 'Down', exact: true })).toHaveAttribute('aria-pressed', 'true');
		await page.getByRole('button', { name: 'Price', exact: true }).click();
		await expect(page).toHaveURL(/sort=price/);
		await expect(page).toHaveURL(/dir=down/);

		await page.getByRole('button', { name: '7d' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveURL(/window=7d.*sort=price|sort=price.*window=7d/);
	});

	// replaceState leaves page.url stale, so Back must restore the view from the
	// address bar (see $lib/urlParams), both from a product page (remount) and
	// between two /movers windows (same component, re-read on navigation).
	test('Back restores the sort, direction and grouping written to the URL (#26)', async ({ page }) => {
		await goto(page, '/movers?window=30d');
		await page.getByRole('button', { name: 'Price', exact: true }).click();
		await page.getByRole('button', { name: 'Per listing' }).click();
		await expect(page).toHaveURL(/sort=price.*group=0/);

		await page.locator('tbody tr a[href^="/product/"]').first().click();
		await expect(page).toHaveURL(/\/product\/\d+$/);
		await page.goBack();
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveURL(/window=30d.*sort=price.*group=0/);
		await expect(page.getByRole('button', { name: 'Price', exact: true })).toHaveAttribute('aria-pressed', 'true');
		await expect(page.getByRole('button', { name: 'Per listing' })).toHaveAttribute('aria-pressed', 'true');

		await page.getByRole('button', { name: '7d' }).click();
		await expect(page).toHaveURL(/window=7d/);
		await page.getByRole('button', { name: '% change' }).click();
		await expect(page).toHaveURL(/window=7d.*sort=pct/);
		await page.goBack();
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveURL(/window=30d.*sort=price/);
		await expect(page.getByRole('button', { name: 'Price', exact: true })).toHaveAttribute('aria-pressed', 'true');
		await expect(page.getByRole('button', { name: '30d' })).toHaveAttribute('aria-pressed', 'true');
	});

	test('sortable headers expose aria-sort, and every mover renders once (#5 items 5-6)', async ({ page }) => {
		await goto(page, '/movers');
		const newHeader = page.locator('th', { has: page.getByRole('button', { name: /^New/ }) });
		await expect(newHeader).toHaveAttribute('aria-sort', 'none');
		await page.getByRole('button', { name: /^New/ }).click();
		await expect(newHeader).toHaveAttribute('aria-sort', 'ascending');

		// No second, mobile-only copy of the list.
		await expect(page.locator('main ul li a[href^="/product/"]')).toHaveCount(0);
		const html = await (await page.request.get('/movers?group=0')).text();
		const rows = (html.match(/data-testid="mover-row"/g) ?? []).length;
		const links = (html.match(/<td[^>]*>\s*<a href="\/product\/\d+"/g) ?? []).length;
		expect(links).toBe(rows);
	});
});

test.describe('product detail', () => {
	test('renders product meta chips and the chart container', async ({ page }) => {
		// Find a product link from the seed data (product 1 always exists in the temp DB)
		const res = await page.request.get('/product/1');
		expect(res.status()).toBe(200);
await goto(page, '/product/1');

		await expect(page.locator('h1').first()).toBeVisible();
		// Product 1 is an Intel chip — the header shows its brand logo
		await expect(page.locator('svg[aria-label="Intel"]').first()).toBeVisible();
		// The headline's provenance line states listing/snapshot counts and span.
		await expect(page.getByText(/\d+ listings? · \d+ snapshots? ·/)).toBeVisible();
		await expect(page.getByLabel('Price history chart')).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Offers' })).toBeVisible();
		// Product 1 is an Intel current-gen chip — the Generation chip shows the
		// friendly architecture name, not the raw tier code.
		// Scoped to the meta line: the breadcrumb (#26) also names the generation.
		await expect(page.getByTestId('product-meta')).toContainText('Core Ultra 200 (Arrow Lake)');
	});

	test('chart skeleton resolves once the chart mounts client-side', async ({ page }) => {
		// The server-rendered HTML ships the skeleton (the chart can only
		// draw after hydration)...
		const res = await page.request.get('/product/1');
		expect(res.status()).toBe(200);
		expect(await res.text()).toContain('chart-skeleton');
		// ...and it is gone once uPlot has mounted.
		await goto(page, '/product/1');
		await expect(page.locator('.chart-skeleton')).toHaveCount(0);
	});

	test('shows the cheapest-price range and an honest average delta', async ({ page }) => {
		await goto(page, '/product/1');
		// Both ends of the bar come from the cheapest-per-day series, so the
		// labels say so rather than implying the dearest listing on the shelf.
		await expect(page.getByText('Lowest day', { exact: true })).toBeVisible();
		await expect(page.getByText('Highest day', { exact: true })).toBeVisible();
		await expect(page.getByText(/Range of the cheapest price across \d+ days/)).toBeVisible();
		// The headline's vs-30d-average delta, next to the current price (offer
		// rows also show a per-row vs-30d-avg delta, so scope to the first match).
		// The label must state the days actually behind the average, never a flat 30.
		await expect(page.getByText(/vs \d+-day avg/).first()).toBeVisible();
		await expect(page.getByText(/vs 30d avg/)).toHaveCount(0);
	});

	test('shows when the product was last updated', async ({ page }) => {
		await goto(page, '/product/1');
		await expect(page.getByText(/^Updated /)).toBeVisible();
		await expect(page.getByText(/^Updated (just now|\d+[mh] ago|1 day ago|\d+ days ago)$/)).toBeVisible();
	});

	test('404 for an unknown product id', async ({ page }) => {
		const res = await page.request.get('/product/999999');
		expect(res.status()).toBe(404);
	});

	test('breadcrumbs lead back, the category is highlighted, and Compare with… preselects (#26)', async ({
		page
	}) => {
		await goto(page, '/product/1');
		const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' });
		await expect(crumbs.getByRole('link', { name: 'CPUs' })).toHaveAttribute('href', '/products?category=cpu');
		await expect(
			page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'CPUs', exact: true })
		).toHaveAttribute('aria-current', 'page');

		await page.getByRole('link', { name: 'Compare with…' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveURL(/\/products\?category=cpu&compare=1$/);
		await expect(page.getByRole('region', { name: 'Compare bar' })).toContainText('Pick 1 more');
		await expect(page.getByRole('checkbox', { name: /^Compare /, checked: true })).toHaveCount(1);
	});
});

test.describe('product detail offer list', () => {
	async function openGpuProduct(page: Page) {
		await goto(page, '/products?category=gpu');
		// "( 16GB)?": the base card gains its VRAM if a "... 8GB" sibling is tracked (Task 12).
		await page.getByRole('link', { name: /^GeForce RTX 5060 Ti( 16GB)?$/ }).first().click();
	}

	test('product page leads with the cheapest price and caps the offer list', async ({ page }) => {
		// The RTX 5060 Ti is seeded with more than 8 in-stock offers (see
		// openGpuProduct above), so both claims in this test's name are
		// actually exercisable here, unlike /product/1 whose live-scraped
		// listing count varies day to day.
		await openGpuProduct(page);

		// The headline leads with the cheapest in-stock price — it must match
		// the first (cheapest-first-sorted) row in the offer list below it.
		const headlinePrice = (await page.locator('.text-3xl.num').first().textContent())?.trim();
		expect(headlinePrice).toBeTruthy();
		const firstRowPrice = (
			await page.locator('.order-1.w-24').first().textContent()
		)?.trim();
		expect(firstRowPrice).toBe(headlinePrice);

		// In-stock-only is the default and states what it hides.
		await expect(page.getByText(/In stock only \(\d+ of \d+\)/)).toBeVisible();

		// The offer list is capped at 8 rows with an expander stating the true
		// total — it is not just rendering everything it has.
		await expect(page.getByRole('button', { name: /Show all \d+ offers/ })).toBeVisible();
		expect(await page.locator('a', { hasText: 'Buy at' }).count()).toBeLessThanOrEqual(8);

		// Every offer row shows its retailer and links out.
		const firstOffer = page.locator('a', { hasText: 'Buy at' }).first();
		await expect(firstOffer).toHaveAttribute('rel', 'noopener noreferrer');
		await expect(firstOffer).toHaveAttribute('target', '_blank');
	});

	test('offer list expander reveals the full list', async ({ page }) => {
		// The RTX 5060 Ti is seeded (both from live data/ and the synthetic
		// fallback — see e2e/seed.mjs) with more than 8 in-stock offers, so the
		// expander is unconditionally present here, unlike on /product/1 whose
		// live-scraped listing count varies day to day.
		await openGpuProduct(page);
		const expander = page.getByRole('button', { name: /Show all \d+ offers/ });
		await expect(expander).toBeVisible();

		const before = await page.locator('a', { hasText: 'Buy at' }).count();
		await expander.click();
		expect(await page.locator('a', { hasText: 'Buy at' }).count()).toBeGreaterThan(before);
	});

	test('the "In stock only" checkbox actually filters the offer list', async ({ page }) => {
		await openGpuProduct(page);

		// Expand first so the row count reflects the filter, not the 8-row cap.
		await page.getByRole('button', { name: /Show all \d+ offers/ }).click();
		const checkbox = page.getByLabel(/In stock only/);
		await expect(checkbox).toBeChecked();
		const before = await page.locator('a', { hasText: 'Buy at' }).count();

		await checkbox.uncheck();
		const after = await page.locator('a', { hasText: 'Buy at' }).count();
		expect(after).toBeGreaterThan(before);
	});

	test('a facet chip click narrows the offer list', async ({ page }) => {
		await openGpuProduct(page);
		await page.getByRole('button', { name: /Show all \d+ offers/ }).click();
		const before = await page.locator('a', { hasText: 'Buy at' }).count();

		// The RTX 5060 Ti is seeded across both retailers.
		const pccgChip = page.getByRole('button', { name: /^PCCG/ });
		await expect(pccgChip).toBeVisible();
		await expect(pccgChip).toHaveAttribute('aria-pressed', 'false');

		await pccgChip.click();
		await expect(pccgChip).toHaveAttribute('aria-pressed', 'true');
		const after = await page.locator('a', { hasText: 'Buy at' }).count();
		expect(after).toBeLessThan(before);
	});

	test('the "Chart" toggle on an offer row registers the click', async ({ page }) => {
		await goto(page, '/product/1');
		// Scoped by the toggle's stable layout class rather than its text —
		// clicking flips the button's own label ("Chart" -> "On chart"), which
		// would otherwise shift a text-based `.first()` query onto the next row.
		const chartToggle = page.locator('button.order-5').first();
		await expect(chartToggle).toBeVisible();
		await expect(chartToggle).toHaveAttribute('aria-pressed', 'false');

		await chartToggle.click();
		await expect(chartToggle).toHaveAttribute('aria-pressed', 'true');
		await expect(chartToggle).toHaveText('On chart');
		// The chart must survive the overlay toggle (reactive rebuild).
		await expect(page.getByLabel('Price history chart')).toBeVisible();
	});

	test('the chart has a legend, a spoken summary and a data table (#27)', async ({ page }) => {
		await goto(page, '/product/1');
		const chart = page.getByRole('img', { name: /^Price history chart\./ });
		await expect(chart).toBeVisible();
		await expect(chart).toHaveAttribute('aria-label', /cheapest in-stock price|No in-stock price/);
		await expect(page.getByRole('list', { name: 'Chart legend' })).toContainText('Cheapest and dearest');

		const summary = page.locator('summary', { hasText: 'Show price data' });
		await summary.focus();
		await page.keyboard.press('Enter');
		await expect(page.getByRole('table').filter({ hasText: 'Dearest in stock' })).toBeVisible();
	});

	test('the chart shows the 30-day average and the axis note (#27)', async ({ page }) => {
		await goto(page, '/product/1');
		await expect(page.getByRole('list', { name: 'Chart legend' })).toContainText('30-day avg');
		await expect(page.getByText("Axis doesn't start at $0.")).toBeVisible();
	});

	test('re-renders the chart when navigating between products', async ({ page }) => {
		await openGpuProduct(page);
		await expect(page.getByLabel('Price history chart')).toBeVisible();

		// Navigate to a different product via the palette — same route
		// component, so this exercises the client-side-navigation reuse path.
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await dialog.getByRole('combobox', { name: 'Search products' }).fill('rx 7800 xt');
		await page.keyboard.press('Enter');

		await expect(page.getByRole('heading', { name: /Radeon RX 7800 XT/ })).toBeVisible();
		await expect(page.getByLabel('Price history chart')).toBeVisible();
	});

	test('search narrows the offer list by name', async ({ page }) => {
		await openGpuProduct(page);

		await page.getByLabel('Filter offers by name').fill('msi');
		// Scope to offer-row titles (`title` attribute), not the brand facet
		// chips, which always list every brand regardless of the search text.
		await expect(page.locator('span[title]', { hasText: /MSI/i }).first()).toBeVisible();
		await expect(page.locator('span[title]', { hasText: /ASUS/i })).toHaveCount(0);
	});

	// OfferRow renders a delisted listing's last-known price unconditionally —
	// price-hiding for delisted rows was retired on purpose when the brand
	// accordion was replaced by the flat offer list. The "Delisted" badge is
	// now the only disambiguator, so the guarantee this test locks in is: a
	// delisted row's badge and its (still-rendered) price always sit together
	// on the same row — a stale price is never shown unlabelled.
	test('shows a Delisted badge for a delisted listing', async ({ page }) => {
		await openGpuProduct(page);

		await expect(page.getByRole('heading', { name: 'Offers' })).toBeVisible();
		// The delisted listing is never in stock, so it is hidden by the
		// in-stock-only default; turn that off before searching for it.
		await page.getByLabel(/In stock only/).uncheck();
		await page.getByLabel('Filter offers by name').fill('XFX Delisted Demo');

		const delistedRow = page.locator('.divide-y > div', { hasText: 'XFX Delisted Demo 16GB' });
		await expect(delistedRow).toBeVisible();
		// The badge and the price are asserted on the SAME row.
		await expect(delistedRow.getByText('Delisted', { exact: true })).toBeVisible();
		await expect(delistedRow.locator('span.num')).toBeVisible();
	});
});

test.describe('product detail specs', () => {
	test('renders the spec panel below the price content', async ({ page }) => {
		await goto(page, '/product/1');

		const specs = page.getByRole('heading', { name: 'Specs' });
		await expect(specs).toBeVisible();
		await expect(page.getByText('Core Ultra 200S — Arrow Lake')).toBeVisible();
		await expect(page.getByText('10 cores / 10 threads')).toBeVisible();
		await expect(page.getByText('2.5 / 4.8 GHz')).toBeVisible();
		await expect(page.getByText('45 W')).toBeVisible();

		// The spec panel must sit below the price graph, never above it.
		const chartBox = await page.getByLabel('Price history chart').boundingBox();
		const specsBox = await specs.boundingBox();
		expect(chartBox).not.toBeNull();
		expect(specsBox).not.toBeNull();
		expect(specsBox!.y).toBeGreaterThan(chartBox!.y + chartBox!.height);
	});

	test('expands the full specs section on demand', async ({ page }) => {
		await goto(page, '/product/1');

		await expect(page.getByText('LGA1851')).toBeHidden();
		await page.getByText('Show full specs').click();
		await expect(page.getByText('LGA1851')).toBeVisible();
		await expect(page.getByText('24 MB')).toBeVisible();
	});

	test('renders no spec panel when the product has no specs', async ({ page }) => {
		await goto(page, `/product/${productIdByModel('E2E Thin History GPU')}`);
		await expect(page.getByRole('heading', { name: 'Specs' })).toHaveCount(0);
	});

	test('renders the gpu spec fields', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		// "( 16GB)?": the base card gains its VRAM if a "... 8GB" sibling is tracked (Task 12).
		await page.getByRole('link', { name: /^GeForce RTX 5060 Ti( 16GB)?$/ }).first().click();

		await expect(page.getByRole('heading', { name: 'Specs' })).toBeVisible();
		await expect(page.getByText('RTX 50 — Blackwell')).toBeVisible();
		// exact: retailer listing names also contain "16GB GDDR7"
		await expect(page.getByText('16GB GDDR7', { exact: true })).toBeVisible();
		await expect(page.getByText('4,608')).toBeVisible();
		await expect(page.getByText('180 W')).toBeVisible();
	});
});

test.describe('price alerts', () => {
	test('arms an alert from the product page and deletes it again', async ({ page }) => {
		await goto(page, '/product/1');

		// The alert section is present but starts with no armed alerts.
		await expect(page.getByRole('heading', { name: 'Price alerts' })).toBeVisible();
		await expect(page.getByText('My alerts')).toHaveCount(0);

		// Arm an email alert under $500 with restock notification.
		await page.getByLabel('Target price in AUD').fill('500');
		await page.getByLabel('Notification channel').selectOption('email');
		await page.getByLabel('Notify on restock').check();
		await page.getByRole('button', { name: 'Create alert' }).click();
		// Plain form POST -> 303 redirect back to the product page.
		await page.waitForLoadState('networkidle');

		await expect(page.getByText('My alerts')).toBeVisible();
		await expect(page.getByText('Under $500')).toBeVisible();
		await expect(page.getByText('· email')).toBeVisible();
		await expect(page.getByText('· restock')).toBeVisible();

		// Deleting the alert removes it from the list.
		await page.getByRole('button', { name: 'Delete alert' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page.getByText('My alerts')).toHaveCount(0);
	});
});

test.describe('deals', () => {
	test('ranks the deepest discount first and links to the product page', async ({ page }) => {
		await goto(page, '/deals');
		const rows = page.getByTestId('below-average-list').locator('a[href^="/product/"]');
		await expect(rows.first()).toHaveText('E2E Deal Demo GPU');
	});

	// Changed for #6: E2E Deal Demo GPU clears the real-deal floors, so under
	// the dedup rule it now appears ONLY in belowAverage. E2E New Low GPU is
	// the fixture built to earn a new low without clearing those floors, so
	// it is the one that appears here.
	test('lists an at-a-new-low product in its own anchored section, once (#6)', async ({ page }) => {
		await goto(page, '/deals');
		const section = page.locator('#all-time-low');
		await expect(section).toBeVisible();
		await expect(
			section.getByRole('link', { name: 'E2E New Low GPU', exact: true })
		).toBeVisible();
	});

	// #6: a product that clears the real-deal floors is shown only in
	// belowAverage, never duplicated into the at-a-new-low section too.
	test('does not duplicate a below-average deal into the at-a-new-low section (#6)', async ({
		page
	}) => {
		await goto(page, '/deals');
		const rows = page.getByTestId('below-average-list').locator('a[href^="/product/"]');
		await expect(rows.first()).toHaveText('E2E Deal Demo GPU');
		const section = page.locator('#all-time-low');
		await expect(section.getByText('E2E Deal Demo GPU')).toHaveCount(0);
	});

	test('excludes products without enough history to have an average', async ({ page }) => {
		await goto(page, '/deals');
		await expect(page.getByText('E2E Thin History GPU')).toHaveCount(0);
	});

	// #6: the deal-row count must equal the "All" facet count (the page can
	// never claim more rows than it shows), and a below-average row's delta
	// should never read as a near-zero move dressed up as a deal.
	test('shows exactly the deals the facets count, with no near-zero below-average deltas (#6)', async ({
		page
	}) => {
		// Skipped on synthetic data (#13): the CI fixture's non-fixture products
		// barely move over 3 flat/near-flat days, so nothing but the E2E deal
		// fixtures (all retailer 'scorptec') clears the deal threshold and the
		// retailer facet bar never grows a second chip. Only the real scrape's
		// price variance produces that.
		test.skip(SYNTHETIC, 'requires the real scrape\'s retailer/price variety');
		await goto(page, '/deals');
		const rows = page.getByTestId('deal-row');
		const allChip = page.getByRole('button', { name: /^All\s/ }).first();
		await expect(allChip).toBeVisible();
		const allText = (await allChip.textContent()) ?? '';
		const allCount = Number(allText.match(/\d+/)?.[0]);
		expect(Number.isNaN(allCount)).toBe(false);
		await expect(rows).toHaveCount(allCount);

		// Scoped to below-average-list only: that section's implicit claim is
		// "at least 2% below average" (DEAL_MIN_PCT), so its delta can never
		// read as a near-zero move. The at-a-new-low section makes a different
		// claim (an earned all-time low, not a below-average one) and can
		// legitimately show a small or even negative saving on real data — a
		// live run surfaced exactly such a row, which is correct, not a bug.
		const belowAverageTexts = await page
			.getByTestId('below-average-list')
			.getByTestId('deal-row')
			.allTextContents();
		for (const text of belowAverageTexts) {
			// formatPct/formatSignedAud render U+2212 "−", not an ASCII hyphen
			// (fix round 1, I1) — match both so a real −0.1% row is caught.
			expect(text).not.toMatch(/[-−]0\.\d%/);
		}
	});

	test('filtering by retailer narrows the list via the URL', async ({ page }) => {
		// Skipped on synthetic data (#13): see above -- no PCCG deal chip exists
		// without the real scrape's price variance.
		test.skip(SYNTHETIC, 'requires a PCCG deal to exist, which only the real scrape produces');
		await goto(page, '/deals');
		await page.getByRole('button', { name: /^PCCG/ }).click();
		await expect(page).toHaveURL(/retailer=pccg/);
		await expect(
			page.getByTestId('below-average-list').getByText('E2E Deal Demo GPU')
		).toHaveCount(0);
	});

	test('filtering by category to CPUs hides the GPU fixture', async ({ page }) => {
		await goto(page, '/deals?category=cpu');
		await expect(page.getByText('E2E Deal Demo GPU')).toHaveCount(0);
	});
});

test.describe('is now a good time to buy? (#31)', () => {
	test('states the low, the recent spread and where to buy', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		await page.getByRole('link', { name: /^GeForce RTX 5060 Ti( 16GB)?$/ }).first().click();
		await page.waitForLoadState('networkidle');

		const panel = page.getByRole('region', { name: 'Is now a good time to buy?' });
		await expect(panel).toBeVisible();
		await expect(panel.getByTestId('low-summary')).toContainText(/Lowest since|Today is the lowest price since/);
		await expect(panel).not.toContainText('all-time');
		// The stats strip puts the windows across the top (Task 5): 30 / 90 / 180.
		const strip = panel.getByRole('table', { name: /low, median and high/ });
		await expect(strip.getByRole('columnheader', { name: '30 days' })).toBeVisible();
		await expect(strip.getByRole('columnheader', { name: '90 days' })).toBeVisible();
		await expect(strip.getByRole('columnheader', { name: '180 days' })).toBeVisible();
		await expect(strip.getByRole('rowheader', { name: 'Median' })).toBeVisible();
		// The RTX 5060 Ti is seeded at both retailers.
		await expect(panel.getByRole('rowheader', { name: 'Scorptec' })).toBeVisible();
		await expect(panel.getByRole('rowheader', { name: 'PCCG' })).toBeVisible();
		await expect(panel.getByRole('link', { name: /^Buy at \w+ for \$/ }).first()).toHaveAttribute(
			'rel',
			'noopener noreferrer'
		);
	});

	test('a product with two days of history says so instead of summarising (Review Focus 1)', async ({
		page
	}) => {
		await goto(page, '/products?category=gpu');
		const box = page.getByLabel(/^Search GPUs$/);
		await box.fill('E2E Thin History');
		await box.press('Enter');
		await page.waitForLoadState('networkidle');
		const panel = page.getByRole('region', { name: 'Is now a good time to buy?' });
		await expect(panel.getByText('Gathering history (2 days)').first()).toBeVisible();
		await expect(panel).not.toContainText('NaN');
		// Under the gate the history badges collapse into one gathering badge.
		const gathering = panel.getByTestId('signal').filter({ hasText: 'Gathering history (2 days)' });
		await expect(gathering).toHaveCount(1);
		await expect(gathering).toContainText('at least 3 days');
	});

	test('the checklist shows each signal with its evidence and a decorative Lucide icon (Task 5)', async ({
		page
	}) => {
		await goto(page, `/product/${productIdByModel('E2E New Low GPU')}`);
		const panel = page.getByRole('region', { name: 'Is now a good time to buy?' });
		await expect(panel.getByRole('heading', { name: 'Is now a good time to buy?' })).toBeVisible();
		const badges = panel.getByTestId('signal');
		// 5 daily lows 520 -> 500, today 500: percentile, lowest, vs avg and trend.
		expect(await badges.count()).toBeGreaterThanOrEqual(4);
		const lowest = badges.filter({ hasText: 'Lowest since tracking began' });
		await expect(lowest).toContainText('No lower price in 5 tracked days.');
		// avg30 507.40: today is 1.5% under it, inside the neutral +-2% band.
		await expect(badges.filter({ hasText: 'Within 2% of its 30-day average' })).toContainText(
			/against a 30-day average of \$507/
		);
		await expect(badges.filter({ hasText: '7-day trend: falling' })).toContainText('flat is within 1%');
		for (const badge of await badges.all()) {
			await expect(badge.getByTestId('signal-claim')).not.toBeEmpty();
			await expect(badge.getByTestId('signal-evidence')).not.toBeEmpty();
			await expect(badge.locator('svg[aria-hidden="true"]')).toHaveCount(1);
		}
	});

	// The expected events are derived from each fixture's actual snapshot dates,
	// which are anchored to the latest scraped date, so neither test depends on
	// where data/ happens to end (CLAUDE.md determinism).
	test('the chart names the AU sale events inside its date range (Task 5)', async ({ page }) => {
		// The fixture has a day inside EOFY (15-30 June) and recent days, so the
		// plotted range always includes EOFY; the canvas itself cannot be asserted.
		const expected = saleEventsInRange(...productDateRange('E2E Sale Window GPU'));
		expect(expected.map((e) => e.name)).toContain('EOFY');
		await goto(page, `/product/${productIdByModel('E2E Sale Window GPU')}`);
		const legend = page.getByRole('list', { name: 'Chart legend' });
		const hidden = page.getByTestId('chart-sale-events');
		await expect(hidden).toContainText(/Sale events shown: EOFY \(15 Jun/);
		for (const e of expected) {
			// Curated dates not yet announced are marked as estimates (R9).
			const label = e.estimated ? `${e.name} (estimated)` : e.name;
			await expect(legend).toContainText(label);
			await expect(hidden).toContainText(e.estimated ? `${e.name} (estimated, ` : `${e.name} (`);
		}
	});

	test('the chart lists exactly the sale events its range covers (Task 5)', async ({ page }) => {
		const expected = saleEventsInRange(...productDateRange('E2E New Low GPU'));
		await goto(page, `/product/${productIdByModel('E2E New Low GPU')}`);
		const legend = page.getByRole('list', { name: 'Chart legend' });
		if (expected.length === 0) {
			await expect(legend).not.toContainText('Sale events');
			await expect(page.getByTestId('chart-sale-events')).toHaveCount(0);
		} else {
			await expect(legend).toContainText(`Sale events: ${expected.map((e) => (e.estimated ? `${e.name} (estimated)` : e.name)).join(', ')}`);
		}
	});
});

test.describe.serial('/discover (#16)', () => {
	test('lists untracked, requested and conflicts; nav shows a badge', async ({ page }) => {
		await goto(page, '/discover');
		await expect(page.getByRole('heading', { level: 1 })).toHaveText('Discover');
		const untracked = page.getByTestId('discover-untracked');
		await expect(untracked.getByText('GeForce RTX 5050 8GB')).toBeVisible();
		await expect(untracked.getByText('Ryzen 5 5600GT', { exact: true })).toBeVisible();
		await expect(untracked.getByText('NEW', { exact: true })).toHaveCount(1);
		await expect(page.getByTestId('discover-requested').getByText('Core Ultra 7 270K Plus', { exact: true })).toBeVisible();
		await expect(page.getByTestId('discover-conflicts').getByText('Sapphire Pulse RX 9070 GRE 12GB')).toBeVisible();
		await expect(page.getByTestId('nav-discover-badge')).toHaveText('2');
	});

	test('Ignore hides a part; Un-ignore brings it back', async ({ page }) => {
		await goto(page, '/discover');
		const row = page.getByTestId('discover-untracked').locator('li', { hasText: 'Ryzen 5 5600GT' });
		await row.getByRole('button', { name: 'Ignore' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('discover-untracked').getByText('Ryzen 5 5600GT', { exact: true })).toHaveCount(0);
		await page.getByText(/Ignored \(\d+\)/).click();
		const ignored = page.getByTestId('discover-ignored').locator('li', { hasText: 'Ryzen 5 5600GT' });
		await ignored.getByRole('button', { name: 'Un-ignore' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('discover-untracked').getByText('Ryzen 5 5600GT', { exact: true })).toBeVisible();
	});

	test('Track moves a part to Requested with its watchlist row; Untrack reverts', async ({ page }) => {
		await goto(page, '/discover');
		const row = page.getByTestId('discover-untracked').locator('li', { hasText: 'GeForce RTX 5050 8GB' });
		await row.getByRole('button', { name: 'Track' }).click();
		await page.waitForLoadState('networkidle');
		const requested = page.getByTestId('discover-requested');
		await expect(requested.getByText('gpu,NVIDIA,GeForce RTX 5050,8GB,current')).toBeVisible();
		await requested.locator('li', { hasText: 'GeForce RTX 5050 8GB' }).getByRole('button', { name: 'Undo' }).click();
		await page.waitForLoadState('networkidle');
		await expect(page.getByTestId('discover-untracked').getByText('GeForce RTX 5050 8GB')).toBeVisible();
	});
});

// Task 3 (#32): the seed pins two deal fixtures against a 1.5 AUD/USD rate, so
// MSRP in AUD = USD x 1.65: E2E Deal Demo GPU A$100 vs US$399 (85% under),
// E2E New Low GPU A$500 vs US$279 (9% over).
function productDateRange(model: string): [string, string] {
	const db = new Database(path.join(here, 'e2e.db'), { readonly: true });
	try {
		const row = db
			.prepare(
				`SELECT MIN(s.snapshot_date) AS lo, MAX(s.snapshot_date) AS hi
				 FROM price_snapshots s JOIN retailer_listings l ON l.id = s.retailer_listing_id
				 JOIN products p ON p.id = l.product_id WHERE p.model = ?`
			)
			.get(model) as { lo: string; hi: string };
		return [row.lo, row.hi];
	} finally {
		db.close();
	}
}

function productIdByModel(model: string): number {
	const db = new Database(path.join(here, 'e2e.db'), { readonly: true });
	try {
		const row = db.prepare('SELECT id FROM products WHERE model = ?').get(model) as { id: number };
		return row.id;
	} finally {
		db.close();
	}
}

// #34: the seed gives E2E Deal Demo GPU (best in stock A$100) a live $89 deal,
// a live $1,099 deal and an expired $79 one.
test.describe('OzBargain deals (#34)', () => {
	test('the product page lists live deals and marks the one below our best', async ({ page }) => {
		await goto(page, `/product/${productIdByModel('E2E Deal Demo GPU')}`);
		const panel = page.getByRole('region', { name: 'OzBargain deals' });
		await expect(panel.getByRole('heading', { name: 'OzBargain deals' })).toBeVisible();
		const rows = panel.getByTestId('ozb-row');
		await expect(rows).toHaveCount(2);
		await expect(rows.first()).toContainText('$89');
		await expect(rows.first()).toContainText('Below our best');
		await expect(rows.first()).toContainText('+42 / −1');
		await expect(rows.nth(1)).toContainText('$1,099');
		await expect(rows.nth(1)).not.toContainText('Below our best');
		const links = panel.getByRole('link', { name: /View deal/ });
		await expect(links).toHaveCount(2);
		for (const link of await links.all()) {
			const href = (await link.getAttribute('href')) ?? '';
			expect(href).toMatch(/^https:\/\/www\.ozbargain\.com\.au\/node\/\d+$/);
			expect(href).not.toContain('/goto/');
			await expect(link).toHaveAttribute('target', '_blank');
		}

		const toggle = panel.getByRole('button', { name: /expired \(1\)$/ });
		await expect(toggle).toHaveText('Show expired (1)');
		await expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await toggle.click();
		await expect(toggle).toHaveAttribute('aria-expanded', 'true');
		await expect(toggle).toHaveText('Hide expired (1)');
		await expect(page.locator(`#${await toggle.getAttribute('aria-controls')}`)).toBeVisible();
		await expect(rows).toHaveCount(3);
		await expect(rows.nth(2)).toContainText('Expired');
		await expect(rows.nth(2)).toContainText('$79');
	});

	test('a product without deals has no OzBargain panel', async ({ page }) => {
		await goto(page, `/product/${productIdByModel('E2E New Low GPU')}`);
		await expect(page.getByRole('heading', { name: 'OzBargain deals' })).toHaveCount(0);
	});

	test('/deals shows an OzBargain chip linking to the cheaper live deal', async ({ page }) => {
		await goto(page, '/deals');
		const row = page.getByTestId('deal-row').filter({ has: page.getByRole('link', { name: 'E2E Deal Demo GPU', exact: true }) });
		const chip = row.getByTestId('ozb-chip');
		await expect(chip).toHaveText('OzBargain $89');
		await expect(chip).toHaveAttribute('href', 'https://www.ozbargain.com.au/node/910001');
		await expect(chip).toHaveAttribute('target', '_blank');
		await expect(page.getByTestId('ozb-chip')).toHaveCount(1);
	});
});

test.describe('MSRP cues (Task 3)', () => {
	test('the product page states the gap to US launch MSRP and explains it', async ({ page }) => {
		await goto(page, `/product/${productIdByModel('E2E Deal Demo GPU')}`);
		const line = page.getByTestId('msrp-line');
		await expect(line).toContainText('85% under US launch MSRP');
		await expect(line).toContainText('≈A$658 inc. GST');
		const info = line.getByRole('button', { name: 'How the MSRP is converted' });
		await expect(info).toHaveAttribute('aria-expanded', 'false');
		await info.click();
		await expect(info).toHaveAttribute('aria-expanded', 'true');
		const panel = page.locator(`#${await info.getAttribute('aria-controls')}`);
		await expect(panel).toBeVisible();
		await expect(panel).toContainText('US$399');
		await expect(panel).toContainText('AUD/USD');
		await expect(panel).toContainText('GST');
		await page.keyboard.press('Escape');
		await expect(info).toHaveAttribute('aria-expanded', 'false');
		await expect(panel).toBeHidden();
	});

	test('a price above MSRP reads "over"', async ({ page }) => {
		await goto(page, `/product/${productIdByModel('E2E New Low GPU')}`);
		await expect(page.getByTestId('msrp-line')).toContainText('9% over US launch MSRP');
	});

	test('a product without an MSRP shows no MSRP line', async ({ page }) => {
		await goto(page, `/product/${productIdByModel('E2E Thin History GPU')}`);
		await expect(page.getByTestId('msrp-line')).toHaveCount(0);
	});

	test('a catalogue row with history shows the 6-segment range bar and its label', async ({ page }) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await goto(page, '/products?category=gpu');
		const row = page.getByTestId('catalog-row').filter({ hasText: 'E2E New Low GPU' });
		const bar = row.getByTestId('row-range');
		await expect(bar.locator('[data-segment]')).toHaveCount(6);
		await expect(bar.locator('[data-filled="true"]')).toHaveCount(1);
		await expect(bar).toContainText('$500');
		await expect(bar).toContainText('$520');
	});

	for (const width of [1024, 1280]) {
		test(`catalogue rows do not wrap and the page does not scroll sideways at ${width}px`, async ({ page }) => {
			await page.setViewportSize({ width, height: 900 });
			await goto(page, '/products?category=gpu');
			const rows = page.getByTestId('catalog-row');
			await expect(rows.first()).toBeVisible();
			expect(await rows.count()).toBeGreaterThan(1);
			// A wrapped row drops its last cell onto a new line; taller cell text does not.
			const tops = await rows.evaluateAll((els) =>
				els.map((e) => {
					const cells = [...e.querySelectorAll('[role="cell"]')].filter((c) => (c as HTMLElement).offsetParent !== null);
					return Math.abs(cells[0].getBoundingClientRect().top - cells[cells.length - 1].getBoundingClientRect().top);
				})
			);
			for (const t of tops) expect(t).toBeLessThan(20);
			const noScroll = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
			expect(noScroll).toBe(true);
		});
	}

	test('the catalogue sorts by vs MSRP, cheapest against MSRP first', async ({ page }) => {
		await goto(page, '/products?category=gpu&sort=msrp');
		const header = page.getByRole('columnheader', { name: /^vs MSRP/ });
		await expect(header).toHaveAttribute('aria-sort', 'ascending');
		const first = page.getByTestId('catalog-row').first();
		await expect(first.getByRole('link')).toHaveText('E2E Deal Demo GPU 16GB');
		await expect(first.getByTestId('row-msrp')).toContainText('−85%');
		await expect(page.locator('select[name="sort"] option[value="msrp"]').first()).toHaveText('vs MSRP');
	});

	test('/deals?below_msrp=1 lists only deals under MSRP', async ({ page }) => {
		await goto(page, '/deals?below_msrp=1');
		await expect(page.getByRole('button', { name: 'Below MSRP' })).toHaveAttribute('aria-pressed', 'true');
		await expect(page.getByRole('link', { name: 'E2E Deal Demo GPU', exact: true })).toBeVisible();
		await expect(page.getByRole('link', { name: 'E2E New Low GPU', exact: true })).toHaveCount(0);
		const values = await page.getByTestId('deal-msrp-value').allTextContents();
		expect(values.length).toBeGreaterThan(0);
		for (const v of values) expect(v.trim()).toMatch(/^−/);
	});

	test('the Below MSRP toggle writes ?below_msrp=1 and every deal row shows vs MSRP', async ({ page }) => {
		await goto(page, '/deals');
		const rows = page.getByTestId('deal-row');
		await expect(rows.first().getByTestId('deal-msrp-value')).toBeVisible();
		expect(await page.getByTestId('deal-msrp-value').count()).toBe(await rows.count());
		const toggle = page.getByRole('button', { name: 'Below MSRP' });
		await expect(toggle).toHaveAttribute('aria-pressed', 'false');
		await toggle.click();
		await expect(page).toHaveURL(/below_msrp=1/);
		await expect(toggle).toHaveAttribute('aria-pressed', 'true');
		await expect(page.getByRole('link', { name: 'E2E New Low GPU', exact: true })).toHaveCount(0);
	});
});

test.describe('PageHeader on every route (#22)', () => {
	const ROUTES = [
		'/',
		'/products?category=gpu',
		'/product/1',
		'/deals',
		'/movers',
		'/discover',
		'/compare',
		'/changelog',
		'/no-such-page'
	];
	for (const route of ROUTES) {
		test(`${route} has exactly one h1, inside the page header`, async ({ page }) => {
			await goto(page, route);
			await expect(page.locator('h1')).toHaveCount(1);
			await expect(page.locator('[data-testid="page-header"] h1')).toHaveCount(1);
		});
	}

	const widthOf = (page: Page) =>
		page.locator('main').evaluate((el) => getComputedStyle(el).maxWidth);

	for (const route of ['/products?category=gpu', '/deals', '/movers', '/discover']) {
		test(`${route} uses the wide 80rem column`, async ({ page }) => {
			await goto(page, route);
			expect(await widthOf(page)).toBe('1280px');
		});
	}

	test('/changelog keeps the 72rem column', async ({ page }) => {
		await goto(page, '/changelog');
		expect(await widthOf(page)).toBe('1152px');
	});

	// R3: the brand line and product-meta belong to the title, above the rule.
	test('the product page brand line and meta sit inside the page header', async ({ page }) => {
		await goto(page, '/product/1');
		const header = page.getByTestId('page-header');
		await expect(header.getByTestId('product-meta')).toBeVisible();
		await expect(header.getByTestId('product-brand')).toBeVisible();
	});

	test('/products count line keeps tabular numbers', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const sub = page.getByTestId('page-header').locator('p').first();
		await expect(sub).toContainText('tracked');
		expect(await sub.locator('.num').count()).toBe(2);
	});

	test('/deals subtitle says both thresholds must hold', async ({ page }) => {
		await goto(page, '/deals');
		const sub = page.getByTestId('page-header').locator('p').first();
		await expect(sub).toContainText(/at least \d+% and at least \$\d+ below/);
		await expect(sub.locator('strong')).toHaveText('and');
	});
});
