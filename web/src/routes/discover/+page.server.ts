// web/src/routes/discover/+page.server.ts
import { fail, redirect } from '@sveltejs/kit';
import { getDb, getWriteDb } from '$lib/server/db';
import { applyDiscoverAction, getDiscoverPage, isDiscoverAction, localIsoDate } from '$lib/server/discover';
import type { DiscoverAction } from '$lib/types';

// Not memoised: a Track/Ignore click must show on the redirect straight back.
export function load() {
	return { wide: true, ...getDiscoverPage(getDb(), localIsoDate()) };
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

export const actions = {
	ignore: ({ request }) => act(request, 'ignore'),
	unignore: ({ request }) => act(request, 'unignore'),
	track: ({ request }) => act(request, 'track'),
	untrack: ({ request }) => act(request, 'untrack')
};
