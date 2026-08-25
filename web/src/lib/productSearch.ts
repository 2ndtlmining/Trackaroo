// Shared product matching for the /products index and the Ctrl+K palette.
// Two search surfaces over the same catalogue must not rank differently, so
// both call this. Pure, so the ranking rules are pinned by tests rather than
// by whichever component happens to render first.
export interface Searchable {
	model: string;
	brand: string;
	productVariant?: string | null;
}

// Lower is better. A model-side match always beats a brand/variant-only one,
// regardless of where in the string it landed.
const EXACT = 0;
const PREFIX = 1;
const WORD_BOUNDARY = 2;
const SUBSTRING = 3;
const OTHER_FIELD = 4;

function normalise(value: string): string {
	return value.toLowerCase().replace(/\s+/g, ' ').trim();
}

export function terms(query: string): string[] {
	return normalise(query).split(' ').filter(Boolean);
}

export function matchScore(item: Searchable, queryTerms: string[]): number | null {
	if (queryTerms.length === 0) return SUBSTRING;
	const model = normalise(item.model);
	const other = normalise(`${item.brand} ${item.productVariant ?? ''}`);
	const joined = queryTerms.join(' ');

	// Every term must appear somewhere, so "5070 ti" and "ti 5070" agree.
	for (const term of queryTerms) {
		if (!model.includes(term) && !other.includes(term)) return null;
	}

	if (model === joined) return EXACT;
	if (model.startsWith(joined)) return PREFIX;
	if (model.includes(` ${joined}`)) return WORD_BOUNDARY;
	if (model.includes(joined)) return SUBSTRING;
	// Terms present but scattered across the model still beat a match that
	// only exists in the brand or variant.
	if (queryTerms.every((t) => model.includes(t))) return SUBSTRING;
	return OTHER_FIELD;
}

export function searchProducts<T extends Searchable>(items: T[], query: string): T[] {
	const queryTerms = terms(query);
	if (queryTerms.length === 0) return [...items];
	return items
		.map((item) => ({ item, score: matchScore(item, queryTerms) }))
		.filter((r): r is { item: T; score: number } => r.score !== null)
		.sort((a, b) => a.score - b.score || a.item.model.localeCompare(b.item.model))
		.map((r) => r.item);
}
