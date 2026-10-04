import type { HandleServerError } from '@sveltejs/kit';
import { classifyServerError } from '$lib/server/errors';

/**
 * Server-side error handling.
 *
 * Unexpected throws (most often better-sqlite3 failing to open or read
 * trackaroo.db) previously surfaced as a bare 500 with no server-side log line,
 * which made "the dashboard is broken" impossible to diagnose without
 * reproducing it. Log the real error, and hand the page a message specific
 * enough for +error.svelte to offer the right fix.
 */
export const handleError: HandleServerError = ({ error, event, status }) => {
	// Expected HTTP errors (error(404, ...) etc.) are already meaningful.
	if (status < 500) {
		return { message: error instanceof Error ? error.message : String(error) };
	}

	const detail = error instanceof Error ? error.message : String(error);
	console.error(`[trackaroo] ${status} on ${event.url.pathname}: ${detail}`);
	if (error instanceof Error && error.stack) console.error(error.stack);

	return classifyServerError(detail);
};
