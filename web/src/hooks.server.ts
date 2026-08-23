import type { HandleServerError } from '@sveltejs/kit';

/**
 * Server-side error handling.
 *
 * Unexpected throws (most often better-sqlite3 failing to open or read
 * trackaroo.db) previously surfaced as a bare 500 with no server-side log line,
 * which made "the dashboard is broken" impossible to diagnose without
 * reproducing it. Log the real error, and hand the page a message specific
 * enough for +error.svelte to offer the right fix.
 */
export const handleServerError: HandleServerError = ({ error, event, status }) => {
	// Expected HTTP errors (error(404, ...) etc.) are already meaningful.
	if (status < 500) {
		return { message: error instanceof Error ? error.message : String(error) };
	}

	const detail = error instanceof Error ? error.message : String(error);
	console.error(`[trackaroo] ${status} on ${event.url.pathname}: ${detail}`);
	if (error instanceof Error && error.stack) console.error(error.stack);

	// Database problems are the realistic 500 here and are self-inflicted often
	// enough (fresh checkout, wrong TRACKAROO_DB, un-migrated DB) that naming
	// them beats a generic message.
	if (/no such file|unable to open database|SQLITE_CANTOPEN/i.test(detail)) {
		return { message: 'The Trackaroo database could not be opened.' };
	}
	if (/no such table/i.test(detail)) {
		return { message: 'The Trackaroo database schema is out of date.' };
	}
	if (/database is locked/i.test(detail)) {
		return { message: 'The database is busy — a pipeline run may be writing. Try again shortly.' };
	}

	return { message: 'Unexpected server error.' };
};
