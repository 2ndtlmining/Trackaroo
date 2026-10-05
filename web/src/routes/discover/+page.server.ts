// web/src/routes/discover/+page.server.ts
import { fail, redirect } from '@sveltejs/kit';
import { getDb, getWriteDb } from '$lib/server/db';
import { applyDiscoverAction, getDiscoverPage, isDiscoverAction, localIsoDate } from '$lib/server/discover';
import { applyRetireAction, getRetireSuggestions, isRetireAction } from '$lib/server/retire';
import type { DiscoverAction, RetireAction } from '$lib/types';

// Not memoised: a Track/Ignore click must show on the redirect straight back.
export function load() {
	const db = getDb();
	const today = localIsoDate();
	return { wide: true, ...getDiscoverPage(db, today), retire: getRetireSuggestions(db, today) };
}

async function act(request: Request, action: DiscoverAction) {
	const form = await request.formData();
	const id = Number(form.get('id'));
	if (!Number.isInteger(id) || id <= 0 || !isDiscoverAction(action)) {
		return fail(400, { error: 'Unknown part.' });
	}
	const now = new Date();
	const result = applyDiscoverAction(getWriteDb(), id, action, `${localIsoDate(now)}T${now.toTimeString().slice(0, 8)}`);
	if (result === 'not-found') return fail(404, { error: 'That part no longer exists.' });
	if (result === 'invalid') return fail(400, { error: 'That change is not possible from its current state.' });
	redirect(303, '/discover');
}

async function actRetire(request: Request, action: RetireAction) {
	const form = await request.formData();
	const id = Number(form.get('productId'));
	if (!Number.isInteger(id) || id <= 0 || !isRetireAction(action)) {
		return fail(400, { error: 'Unknown product.' });
	}
	const result = applyRetireAction(getWriteDb(), id, action, localIsoDate());
	if (result === 'not-found') return fail(404, { error: 'That suggestion no longer exists.' });
	if (result === 'invalid') return fail(400, { error: 'That change is not possible from its current state.' });
	redirect(303, '/discover');
}

export const actions = {
	retire: ({ request }) => actRetire(request, 'retire'),
	keep: ({ request }) => actRetire(request, 'keep'),
	undoRetire: ({ request }) => actRetire(request, 'undo'),
	ignore: ({ request }) => act(request, 'ignore'),
	unignore: ({ request }) => act(request, 'unignore'),
	track: ({ request }) => act(request, 'track'),
	untrack: ({ request }) => act(request, 'untrack')
};
