import { test, expect, type Page } from '@playwright/test';
import Database from 'better-sqlite3';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

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
	test('header links navigate between pages', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByRole('link', { name: 'Products' })).toBeVisible();
		await page.getByRole('link', { name: 'Products' }).click();
		await expect(page).toHaveTitle('Trackaroo — Products');
		await expect(page.getByRole('heading', { name: /Products/i })).toBeVisible();

		await page.getByRole('link', { name: 'Movers' }).click();
		await expect(page).toHaveTitle('Trackaroo — Movers');
		await expect(page.getByRole('heading', { name: 'Movers' })).toBeVisible();

		await page.getByRole('link', { name: 'Dashboard', exact: false }).first().click();
		await expect(page).toHaveTitle('Trackaroo — Dashboard');
	});

test('footer shows the product tagline on every page', async ({ page }) => {
		await goto(page, '/products');
		await expect(page.getByText('Trackaroo — AU CPU & GPU price tracker')).toBeVisible();
		await expect(page.getByText('Logos are trademarks of their respective owners')).toBeVisible();
	});

	test('header shows snapshot stats and lends context', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByText(/\d{4}-\d{2}-\d{2}/)).toBeVisible();
		await expect(page.getByTitle('Most recent price snapshot date')).toBeVisible();
		await expect(page.getByTitle('Distinct days with a snapshot')).toBeVisible();
		await expect(page.getByTitle('SQLite database size')).toBeVisible();
	});
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
});

test.describe('dashboard', () => {
	test('renders the cheapest-deals carousel with a GPU/CPU toggle', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByText('Cheapest deals')).toBeVisible();

		const gpuTab = page.getByRole('tab', { name: 'GPU' });
		await expect(gpuTab).toBeVisible();
		await expect(gpuTab).toHaveAttribute('aria-selected', 'true');

		const firstCard = page.getByRole('listitem').first();
		await expect(firstCard).toBeVisible();
		await expect(firstCard).toContainText('$');

		await page.getByRole('tab', { name: 'CPU' }).click();
		await expect(page.getByRole('tab', { name: 'CPU' })).toHaveAttribute('aria-selected', 'true');
		await expect(page.getByRole('tab', { name: 'GPU' })).toHaveAttribute('aria-selected', 'false');
		await expect(page.getByRole('listitem').first()).toBeVisible();
	});

	test('flags deal cards at their 90-day low', async ({ page }) => {
		await goto(page, '/');
		// The seeded data has several models whose current price equals the
		// lowest in-stock price over the available history.
		await expect(page.getByText('90d low').first()).toBeVisible();
		await expect(page.getByText('90d low').first()).toHaveAttribute(
			'title',
			'Lowest price in the last 90 days'
		);
	});

	test('renders the four stat tiles from the seeded data', async ({ page }) => {
		await goto(page, '/');
		await expect(page.getByText('Tracked products')).toBeVisible();
		await expect(page.getByText('Listings today')).toBeVisible();
		await expect(page.getByText('Retailers', { exact: true })).toBeVisible();
		await expect(page.getByText('Biggest mover (24h)')).toBeVisible();
	});

	test('renders a populated listings table', async ({ page }) => {
		await goto(page, '/');
		const table = page.locator('table');
		await expect(table).toBeVisible();
		// Seeded data has both CPU and GPU rows across both retailers
await expect(table.getByRole('columnheader', { name: 'Model' })).toBeVisible();
		await expect(table.getByRole('columnheader', { name: 'Price' })).toBeVisible();
		await expect(table.getByRole('columnheader', { name: 'Trend' })).toBeVisible();
		await expect(table.locator('tbody tr').first()).toBeVisible();
		await expect(table.locator('tbody svg').first()).toBeVisible();
		expect(await table.locator('tbody svg polyline').count()).toBeGreaterThan(0);
	});

	test('column headers sort the table via the tri-state cycle', async ({ page }) => {
		await goto(page, '/');
		const priceHeader = page.getByRole('button', { name: /^Price/ });
		await expect(priceHeader).toBeVisible();
		// unsorted -> ascending -> descending -> unsorted
		await priceHeader.click();
		await expect(priceHeader).toContainText('▲');
		await priceHeader.click();
		await expect(priceHeader).toContainText('▼');
		await priceHeader.click();
		await expect(priceHeader).not.toContainText('▲');
		await expect(priceHeader).not.toContainText('▼');
	});

	test('filters the table by category via the URL', async ({ page }) => {
		await goto(page, '/');
		const categorySelect = page.getByLabel('Filter by category');
		await categorySelect.selectOption('gpu');
		await expect(page).toHaveURL(/\/\?category=gpu/);

		const firstRow = page.locator('tbody tr').first();
		await expect(firstRow).toContainText('GPU');
	});

	test('filters the table by retailer via the URL', async ({ page }) => {
		await goto(page, '/');
		const retailerSelect = page.getByLabel('Filter by retailer');
		await retailerSelect.selectOption('scorptec');
		await expect(page).toHaveURL(/\/\?retailer=scorptec/);

		const rows = page.locator('tbody tr');
		await expect(rows.first()).toBeVisible();
		const retailerCells = rows.locator('td').nth(2);
		const count = await retailerCells.count();
		expect(count).toBeGreaterThan(0);
		for (let i = 0; i < count; i += 1) {
			await expect(retailerCells.nth(i)).toHaveText('scorptec');
		}
	});

	test('filters by generation tier via the URL', async ({ page }) => {
		await goto(page, '/');
		const tierSelect = page.getByLabel('Filter by generation tier');
		await tierSelect.selectOption('current-2');
		await expect(page).toHaveURL(/\/\?tier=current-2/);
		await expect(page.locator('tbody tr').first()).toBeVisible();
	});

	test('search narrows the table to matching models', async ({ page }) => {
		await goto(page, '/');
		const searchBox = page.getByLabel('Search by model');
		await searchBox.fill('5600');
		await expect(page).toHaveURL(/\/\?q=5600/);
		const rows = page.locator('tbody tr');
		await expect(rows.first()).toBeVisible();
		const count = await rows.count();
		expect(count).toBeGreaterThan(0);
		const text = await rows.first().textContent();
		expect(text).toContain('5600');
	});

	test('sort by price ascending orders cheapest first', async ({ page }) => {
		await goto(page, '/?category=gpu');
		const sortSelect = page.getByLabel('Sort by price');
		await sortSelect.selectOption('price-asc');
		await expect(page).toHaveURL(/\/\?category=gpu&sort=price-asc/);
		const firstCell = page.locator('tbody tr td').nth(4).first();
		await expect(firstCell).toBeVisible();
		const first = await firstCell.textContent();
		await sortSelect.selectOption('price-desc');
		await expect(page).toHaveURL(/\/\?category=gpu&sort=price-desc/);
		await expect(firstCell).not.toHaveText(first ?? '');
	});

	test('clear filters removes the query string', async ({ page }) => {
		await goto(page, '/?category=gpu');
		await page.getByRole('button', { name: 'Clear filters' }).click();
		await expect(page).toHaveURL('/');
		await expect(page.getByText('Tracked products')).toBeVisible();
	});

	test('in-stock filter keeps only in-stock rows', async ({ page }) => {
		await goto(page, '/');
		await page.getByLabel('In stock only').check();
		await expect(page).toHaveURL(/\/\?in_stock=1/);
		const rows = page.locator('tbody tr');
		const count = await rows.count();
		expect(count).toBeGreaterThan(0);
		for (let i = 0; i < count; i += 1) {
			await expect(rows.nth(i)).toContainText('In stock');
		}
	});
});

test.describe('products page', () => {
	test('shows the products heading and a card grid', async ({ page }) => {
		await goto(page, '/products');
		await expect(page.getByRole('heading', { name: /Products/i })).toBeVisible();
		const cards = page.locator('article');
		expect(await cards.count()).toBeGreaterThan(0);
		// Each card shows the model name and a "from $" price (or no-in-stock note)
		await expect(cards.first()).toContainText(/from \$|No in-stock listings/);
		// Brand logo icons render on the cards (AMD/NVIDIA/Intel seeded)
		await expect(page.locator('svg[aria-label="AMD"]').first()).toBeVisible();
		await expect(page.locator('svg[aria-label="NVIDIA"]').first()).toBeVisible();
		await expect(page.locator('svg[aria-label="Intel"]').first()).toBeVisible();
		// At least one unexpanded card shows a trend sparkline (cards with history)
		const sparklineCard = cards.filter({ has: page.locator('svg polyline') }).first();
		expect(await sparklineCard.count()).toBeGreaterThan(0);
		await expect(
			sparklineCard.locator('svg').filter({ has: page.locator('polyline') }).first()
		).toBeVisible();
	});

	test('shows an empty state when no filters match', async ({ page }) => {
		await goto(page, '/products?brand=NoSuchBrandXYZ');
		await expect(
			page.getByText('No listings match the current filters.')
		).toBeVisible();
	});

	test('expands a product card to reveal its variant listings', async ({ page }) => {
		await goto(page, '/products');
		const card = page.locator('article').filter({ hasText: 'RTX 5060 Ti' }).first();
		await expect(card).toBeVisible();
		const toggle = card.getByRole('button', { name: /listing/i });
		await expect(card.locator('table')).toHaveCount(0);

		await toggle.click();
		await expect(card.locator('table')).toBeVisible();
		await expect(toggle).toHaveText(/Hide listings/);

await toggle.click();
		await expect(card.locator('table')).toHaveCount(0);
	});

	test('shows a trend sparkline column once a card is expanded', async ({ page }) => {
		await goto(page, '/products');
		const card = page.locator('article').first();
		await expect(card).toBeVisible();
		await card.getByRole('button', { name: /listing/i }).click();
		await expect(card.locator('table')).toBeVisible();
		await expect(card.locator('table thead th').filter({ hasText: 'Trend' })).toBeVisible();
		await expect(card.locator('table svg').first()).toBeVisible();
		expect(await card.locator('table svg polyline').count()).toBeGreaterThan(0);
	});

	test('flags products whose cheapest in-stock price is below the 30-day average', async ({
		page
	}) => {
		await goto(page, '/products');
		const { dealIds, nonDealId } = expectedDeals();
		expect(dealIds.length).toBeGreaterThan(0);
		// Exactly the expected products carry a Deal badge.
		await expect(page.getByText('Deal', { exact: true })).toHaveCount(dealIds.length);
		for (const id of dealIds) {
			await expect(
				page.locator('article', { has: page.locator(`a[href="/product/${id}"]`) })
			).toContainText('Deal');
		}
		// An in-stock product that is NOT a deal must not be flagged.
		if (nonDealId !== null) {
			await expect(
				page.locator('article', { has: page.locator(`a[href="/product/${nonDealId}"]`) })
			).not.toContainText('Deal');
		}
	});
});

test.describe('command palette', () => {
	test('opens with Ctrl+K, searches and navigates to a product on Enter', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await expect(dialog).toBeVisible();
		await expect(dialog.getByRole('textbox', { name: 'Search products' })).toBeFocused();

		await dialog.getByRole('textbox', { name: 'Search products' }).fill('7600');
		const first = dialog.getByRole('option').first();
		await expect(first).toContainText('Ryzen 5 7600');
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL(/\/product\/\d+$/);
		await expect(page.getByRole('heading', { name: /Ryzen 5 7600/ })).toBeVisible();
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
		await dialog.getByRole('textbox', { name: 'Search products' }).fill('RTX 5060');
		await expect(dialog.getByRole('option').first()).toContainText('Compare');
	});

	test('shows a snapshot count badge on each result', async ({ page }) => {
		await goto(page, '/');
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await dialog.getByRole('textbox', { name: 'Search products' }).fill('RTX 5060');
		await expect(dialog.getByText(/snapshots/).first()).toBeVisible();
		await expect(dialog.getByText(/snapshots/)).toHaveCount(2);
	});
});

test.describe('compare', () => {
	test('selecting two products in a category enables the compare bar and opens /compare', async ({ page }) => {
		await goto(page, '/products');
		const gpuCards = page.locator('article').filter({ hasText: 'GPU' });
		await expect(gpuCards.first()).toBeVisible();
		await gpuCards.nth(0).getByRole('checkbox').check();
		await gpuCards.nth(1).getByRole('checkbox').check();

		const bar = page.getByRole('region', { name: 'Compare bar' });
		await expect(bar).toBeVisible();
		await bar.getByRole('link', { name: /Compare \(2\)/ }).click();

		await expect(page).toHaveURL(/\/compare\?ids=\d+,\d+$/);
		await expect(page.getByRole('heading', { name: 'Compare' })).toBeVisible();
		// Two product columns plus the "Field" header
		await expect(page.locator('thead th a')).toHaveCount(2);
		// Each column header shows a brand logo icon
		await expect(page.locator('thead svg[aria-label]')).toHaveCount(2);
		await expect(page.getByText('Architecture', { exact: true })).toBeVisible();
	});

	test('locks other categories once one category is selected', async ({ page }) => {
		await goto(page, '/products');
		const gpuCard = page.locator('article').filter({ hasText: 'GPU' }).first();
		const cpuCard = page.locator('article').filter({ hasText: 'CPU' }).first();
		await expect(gpuCard).toBeVisible();
		await expect(cpuCard).toBeVisible();

		await gpuCard.getByRole('checkbox').check();
		await expect(cpuCard.getByRole('checkbox')).toBeDisabled();
		// Same-category cards stay enabled
		await expect(
			page.locator('article').filter({ hasText: 'GPU' }).nth(1).getByRole('checkbox')
		).toBeEnabled();
	});

	test('clears the selection from the compare bar', async ({ page }) => {
		await goto(page, '/products');
		const gpuCards = page.locator('article').filter({ hasText: 'GPU' });
		await gpuCards.nth(0).getByRole('checkbox').check();
		await gpuCards.nth(1).getByRole('checkbox').check();

		const bar = page.getByRole('region', { name: 'Compare bar' });
		await bar.getByRole('button', { name: 'Clear' }).click();
		await expect(page.getByRole('region', { name: 'Compare bar' })).toHaveCount(0);
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
		await expect(page.getByRole('button', { name: '7d' })).toHaveClass(/bg-surface-hover/);
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
		await expect(page.getByText('Core Ultra 200 (Arrow Lake)')).toBeVisible();
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

	test('shows all-time low/high and the vs-30d-average delta on the product page', async ({
		page
	}) => {
		await goto(page, '/product/1');
		// Labels on the price-range bar.
		await expect(page.getByText('All-time low', { exact: true })).toBeVisible();
		await expect(page.getByText('All-time high', { exact: true })).toBeVisible();
		// The headline's vs-30d-average delta, next to the current price (offer
		// rows also show a per-row vs-30d-avg delta, so scope to the first match).
		await expect(page.getByText(/vs 30d avg/).first()).toBeVisible();
	});

	test('shows when the product was last updated', async ({ page }) => {
		await goto(page, '/product/1');
		await expect(page.getByText(/^Updated /)).toBeVisible();
		await expect(page.getByText(/^Updated (just now|\d+[mhdw]o? ago|never)$/)).toBeVisible();
	});

	test('404 for an unknown product id', async ({ page }) => {
		const res = await page.request.get('/product/999999');
		expect(res.status()).toBe(404);
	});
});

test.describe('product detail offer list', () => {
	async function openGpuProduct(page: Page) {
		await goto(page, '/products?category=gpu');
		const card = page.locator('article').filter({ hasText: 'RTX 5060 Ti' }).first();
		await card.locator('a').first().click();
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
		expect(await page.locator('a', { hasText: 'View →' }).count()).toBeLessThanOrEqual(8);

		// Every offer row shows its retailer and links out.
		const firstOffer = page.locator('a', { hasText: 'View →' }).first();
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

		const before = await page.locator('a', { hasText: 'View →' }).count();
		await expander.click();
		expect(await page.locator('a', { hasText: 'View →' }).count()).toBeGreaterThan(before);
	});

	test('the "In stock only" checkbox actually filters the offer list', async ({ page }) => {
		await openGpuProduct(page);

		// Expand first so the row count reflects the filter, not the 8-row cap.
		await page.getByRole('button', { name: /Show all \d+ offers/ }).click();
		const checkbox = page.getByLabel(/In stock only/);
		await expect(checkbox).toBeChecked();
		const before = await page.locator('a', { hasText: 'View →' }).count();

		await checkbox.uncheck();
		const after = await page.locator('a', { hasText: 'View →' }).count();
		expect(after).toBeGreaterThan(before);
	});

	test('a facet chip click narrows the offer list', async ({ page }) => {
		await openGpuProduct(page);
		await page.getByRole('button', { name: /Show all \d+ offers/ }).click();
		const before = await page.locator('a', { hasText: 'View →' }).count();

		// The RTX 5060 Ti is seeded across both retailers.
		const pccgChip = page.getByRole('button', { name: /^PCCG/ });
		await expect(pccgChip).toBeVisible();
		await expect(pccgChip).toHaveAttribute('aria-pressed', 'false');

		await pccgChip.click();
		await expect(pccgChip).toHaveAttribute('aria-pressed', 'true');
		const after = await page.locator('a', { hasText: 'View →' }).count();
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

	test('re-renders the chart when navigating between products', async ({ page }) => {
		await openGpuProduct(page);
		await expect(page.getByLabel('Price history chart')).toBeVisible();

		// Navigate to a different product via the palette — same route
		// component, so this exercises the client-side-navigation reuse path.
		await page.keyboard.press('Control+k');
		const dialog = page.getByRole('dialog', { name: 'Search products' });
		await dialog.getByRole('textbox', { name: 'Search products' }).fill('7600');
		await page.keyboard.press('Enter');

		await expect(page.getByRole('heading', { name: /Ryzen 5 7600/ })).toBeVisible();
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
		await goto(page, '/product/2');
		await expect(page.getByRole('heading', { name: 'Specs' })).toHaveCount(0);
	});

	test('renders the gpu spec fields', async ({ page }) => {
		await goto(page, '/products?category=gpu');
		const card = page.locator('article').filter({ hasText: 'RTX 5060 Ti' }).first();
		await card.locator('a').first().click();

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

	test('lists an at-all-time-low product in its own anchored section', async ({ page }) => {
		await goto(page, '/deals');
		const section = page.locator('#all-time-low');
		await expect(section).toBeVisible();
		await expect(section.getByText('E2E Deal Demo GPU')).toBeVisible();
	});

	test('excludes products without enough history to have an average', async ({ page }) => {
		await goto(page, '/deals');
		await expect(page.getByText('E2E Thin History GPU')).toHaveCount(0);
	});

	test('filtering by retailer narrows the list via the URL', async ({ page }) => {
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
