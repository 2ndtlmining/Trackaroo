import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// The release number shown in the footer and /healthz: web/package.json is the
// single source, bumped by release.py at the repo root. Read once when the config
// loads, so restart `vite dev` after a release to see the new number.
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));

export default defineConfig({
	plugins: [sveltekit(), tailwindcss()],
	define: {
		__APP_RELEASE__: JSON.stringify(pkg.version)
	},
	resolve: {
		alias: process.env.VITEST
			? [
					{
						// Under vitest, resolve the client Svelte runtime so component
						// tests can use `mount()` in jsdom. The production build keeps
						// its node/server conditions (this alias is never applied).
						find: /^svelte$/,
						replacement: fileURLToPath(
							new URL('./node_modules/svelte/src/index-client.js', import.meta.url)
						)
					}
				]
			: []
	},
	test: {
		include: ['test/**/*.{test,spec}.{js,ts}'],
		environment: 'jsdom'
	}
});
