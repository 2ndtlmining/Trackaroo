import { error } from '@sveltejs/kit';
import { getComparisonData } from '$lib/server/repos';
import { getDb } from '$lib/server/db';
import { MAX_COMPARE } from '$lib/urlState';
import type { Category } from '$lib/types';

export function load({ url }: { url: URL }) {
	const pickerCategory: Category = url.searchParams.get('category') === 'cpu' ? 'cpu' : 'gpu';
	// Links and the compare bar use ?ids=A,B; the empty-state picker is a plain
	// GET form with two <select name="id"> and submits ?id=A&id=B (#26, U-D15).
	const picked = url.searchParams.getAll('id');
	const raw = [url.searchParams.get('ids') ?? '', ...picked].filter((s) => s.trim() !== '').join(',');
	const ids = [...new Set(raw.split(',').map((s) => Number(s.trim())).filter(Number.isInteger))].filter(
		(n) => n > 0
	);

	// Compare is in the nav, so it must open with nothing selected.
	if (raw.trim() === '' && ids.length === 0) {
		return { entries: [], pickerCategory, pickerError: null };
	}
	// The picker with one product chosen twice: ask again rather than 400
	// (Review Focus 3). A hand-built ?ids=5 link is still a malformed request.
	if (picked.length > 0 && ids.length < 2) {
		return { entries: [], pickerCategory, pickerError: 'Pick two different products to compare.' };
	}

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

	return { entries, pickerCategory: entries[0].product.category, pickerError: null };
}
