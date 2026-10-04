// @vitest-environment node
// #29 item 1: the hook rewrote the database messages before +error.svelte
// tested them, so the setup hints could never show. The hook now sets a
// machine-readable code and the page switches on it.
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { classifyServerError } from '../src/lib/server/errors';
import { errorHint } from '../src/lib/errorHints';

describe('classifyServerError', () => {
	it.each([
		['unable to open database file', 'db_missing'],
		['Cannot open database because the directory does not exist', 'db_missing'],
		['SQLITE_CANTOPEN: unable to open', 'db_missing'],
		["ENOENT: no such file or directory, open 'db/trackaroo.db'", 'db_missing'],
		['no such table: price_snapshots', 'db_schema'],
		['database is locked', 'db_locked']
	])('maps %j to %s', (detail, code) => {
		const e = classifyServerError(detail);
		expect(e.code).toBe(code);
		expect(e.message).not.toBe('');
	});

	it('gives no code for anything else', () => {
		expect(classifyServerError('TypeError: x is undefined')).toEqual({
			message: 'Unexpected server error.'
		});
	});
});

describe('hooks.server.ts', () => {
	it('exports the hook under the name SvelteKit calls (handleError)', async () => {
		// It was exported as handleServerError (the TYPE's name), so SvelteKit
		// never called it: every 500 said "Internal Error" with no hint (#29).
		const hooks = await import('../src/hooks.server');
		expect(typeof (hooks as Record<string, unknown>).handleError).toBe('function');
	});

	it('passes the classified error (message and code) to the page', async () => {
		const { handleError } = (await import('../src/hooks.server')) as unknown as {
			handleError: (input: unknown) => App.Error;
		};
		const quiet = console.error;
		console.error = () => {};
		try {
			const out = handleError({
				error: new Error('Cannot open database because the directory does not exist'),
				event: { url: new URL('http://x/') },
				status: 500,
				message: 'Internal Error'
			});
			expect(out).toEqual({ message: 'The Trackaroo database could not be opened.', code: 'db_missing' });
		} finally {
			console.error = quiet;
		}
	});
});

describe('errorHint', () => {
	it('every database code gets its own fix, reachable from the classified error', () => {
		for (const detail of ['unable to open database file', 'no such table: x', 'database is locked']) {
			const e = classifyServerError(detail);
			expect(errorHint(500, e)).toMatch(/seed\.py|migrate\.py|pipeline/);
		}
		expect(errorHint(500, classifyServerError('unable to open database file'))).toContain('seed.py');
		expect(errorHint(500, classifyServerError('no such table: x'))).toContain('migrate.py');
	});

	it('keeps the status-based hints', () => {
		expect(errorHint(404, { message: 'Not found' })).toMatch(/does not exist/);
		expect(errorHint(400, { message: 'Bad' })).toMatch(/malformed/);
		expect(errorHint(500, { message: 'Unexpected server error.' })).toMatch(/server log/);
		expect(errorHint(418, { message: 'x' })).toBeNull();
	});
});

describe('src/error.html (root layout failures)', () => {
	const html = fs.readFileSync(path.resolve(__dirname, '../src/error.html'), 'utf-8');

	it('shows the status and message SvelteKit passes in', () => {
		expect(html).toContain('%sveltekit.status%');
		expect(html).toContain('%sveltekit.error.message%');
	});

	it('carries the database setup hint, styled for both themes, with no external assets', () => {
		expect(html).toContain('seed.py');
		expect(html).toMatch(/prefers-color-scheme/);
		expect(html).not.toMatch(/<link[^>]+stylesheet|<script[^>]+src=/);
	});
});
