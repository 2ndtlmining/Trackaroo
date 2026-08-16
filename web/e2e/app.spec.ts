import { test, expect, type Page } from '@playwright/test';

async function goto(page: Page, path: string) {
	await page.goto(path);
	// Wait for Svelte to finish hydrating so click/select handlers are attached
	await page.waitForLoadState('networkidle');
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
		await expect(table.locator('tbody tr').first()).toBeVisible();
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
});

test.describe('products page', () => {
	test('shows the products heading and a table', async ({ page }) => {
		await goto(page, '/products');
		await expect(page.getByRole('heading', { name: /Products/i })).toBeVisible();
		await expect(page.locator('tbody tr').first()).toBeVisible();
	});

	test('shows an empty state when no filters match', async ({ page }) => {
		await goto(page, '/products?brand=NoSuchBrandXYZ');
		await expect(
			page.getByText('No listings match the current filters.')
		).toBeVisible();
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
});

test.describe('product detail', () => {
	test('renders product meta chips and the chart container', async ({ page }) => {
		// Find a product link from the seed data (product 1 always exists in the temp DB)
		const res = await page.request.get('/product/1');
		expect(res.status()).toBe(200);
		await goto(page, '/product/1');

		await expect(page.locator('h1').first()).toBeVisible();
		await expect(page.getByText('Category', { exact: true })).toBeVisible();
		await expect(page.getByText('Listings', { exact: true })).toBeVisible();
		await expect(page.getByText('History span', { exact: true })).toBeVisible();
		await expect(page.getByLabel('Price history chart')).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Retailer listings' })).toBeVisible();
	});

	test('404 for an unknown product id', async ({ page }) => {
		const res = await page.request.get('/product/999999');
		expect(res.status()).toBe(404);
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
		const row = page.locator('tbody tr').filter({ hasText: 'RTX 5060 Ti' }).first();
		await row.locator('a').click();

		await expect(page.getByRole('heading', { name: 'Specs' })).toBeVisible();
		await expect(page.getByText('RTX 50 — Blackwell')).toBeVisible();
		// exact: retailer listing names also contain "16GB GDDR7"
		await expect(page.getByText('16GB GDDR7', { exact: true })).toBeVisible();
		await expect(page.getByText('4,608')).toBeVisible();
		await expect(page.getByText('180 W')).toBeVisible();
	});
});
