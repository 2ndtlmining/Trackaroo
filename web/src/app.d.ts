declare global {
	// Replaced at build time by vite.config.js `define` (web/package.json version).
	const __APP_RELEASE__: string;

	namespace App {
		interface Error {
			message: string;
			/**
			 * Set by hooks.server.ts for the database failures it recognises, so
			 * +error.svelte can offer the right fix (#29). The message is already
			 * rewritten for people, so it cannot be matched on.
			 */
			code?: 'db_missing' | 'db_schema' | 'db_locked';
		}
	}
}

export {};
