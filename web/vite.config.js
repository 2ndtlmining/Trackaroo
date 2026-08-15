import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit(), tailwindcss()],
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
