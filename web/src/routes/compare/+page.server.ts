import { error } from '@sveltejs/kit';
import { getComparisonData } from '$lib/server/repos';
import { getDb } from '$lib/server/db';

const MAX_COMPARE = 4;

export function load({ url }: { url: URL }) {
	const raw = url.searchParams.get('ids') ?? '';
	const ids = [...new Set(raw.split(',').map((s) => Number(s.trim())).filter(Number.isInteger))].filter(
		(n) => n > 0
	);

	if (ids.length < 2) {
		error(400, 'Select at least 2 products to compare');
	}
	if (ids.length > MAX_COMPARE) {
		error(400, `Compare up to ${MAX_COMPARE} products at once`);
	}

	const db = getDb();
	const entries = getComparisonData(db, ids);
	if (entries.length !== ids.length) {
		error(404, 'One or more products could not be found');
	}

	const categories = new Set(entries.map((e) => e.product.category));
	if (categories.size > 1) {
		error(400, 'Only products in the same category can be compared side by side');
	}

	return { entries };
}