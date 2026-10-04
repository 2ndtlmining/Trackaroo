// The "how to fix it" line under +error.svelte's message. Switches on the
// code hooks.server.ts sets (#29): matching the message never worked, because
// the hook had already rewritten it.
export function errorHint(status: number, error: App.Error | null): string | null {
	if (status === 404) return 'The page or product you asked for does not exist.';
	if (status === 400) return 'That link looks malformed — check the query parameters.';
	switch (error?.code) {
		case 'db_missing':
			return 'Run `python seed.py` (and `python run_daily.py` for data), or check that TRACKAROO_DB points at the right file.';
		case 'db_schema':
			return 'The database is missing a table. Run `python migrate.py` to bring the schema up to date.';
		case 'db_locked':
			return 'A pipeline run is writing to the database; this clears by itself in a moment.';
	}
	if (status >= 500) return 'The server hit an unexpected error. The details are in the server log.';
	return null;
}
