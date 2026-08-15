import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

// The E2E suite runs against a deterministic DB seeded from the repo's
// data/*.json snapshots. e2e/seed.mjs writes it to this fixed path and the
// dev server picks it up via TRACKAROO_DB. It must live outside Playwright's
// `test-results` output dir, which is wiped at run start, and be seeded
// *before* the server boots (globalSetup runs too late for that).
const E2E_DB = path.join(here, 'e2e', 'e2e.db');

export default defineConfig({
	testDir: './e2e',
	fullyParallel: false,
	retries: 0,
	workers: 1,
	reporter: [['list']],
	use: {
		baseURL: 'http://localhost:4174',
		trace: 'on-first-retry',
		screenshot: 'only-on-failure'
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
	webServer: {
		command: `node e2e/seed.mjs && npm run dev -- --port 4174 --strictPort`,
		url: 'http://localhost:4174',
		reuseExistingServer: !process.env.CI,
		timeout: 120_000,
		env: {
			TRACKAROO_DB: E2E_DB
		}
	}
});