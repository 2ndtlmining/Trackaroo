// Turns an unexpected server error into the App.Error the page sees (#29).
// Database problems are the realistic 500 here and are self-inflicted often
// enough (fresh checkout, wrong TRACKAROO_DB, un-migrated DB) that naming them
// beats a generic message. The code carries the kind; the message is for people.
export function classifyServerError(detail: string): App.Error {
	if (/no such file|unable to open database|cannot open database|SQLITE_CANTOPEN/i.test(detail)) {
		return { message: 'The Trackaroo database could not be opened.', code: 'db_missing' };
	}
	if (/no such table/i.test(detail)) {
		return { message: 'The Trackaroo database schema is out of date.', code: 'db_schema' };
	}
	if (/database is locked/i.test(detail)) {
		return {
			message: 'The database is busy — a pipeline run may be writing. Try again shortly.',
			code: 'db_locked'
		};
	}
	return { message: 'Unexpected server error.' };
}
