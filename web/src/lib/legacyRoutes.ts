import type { Category } from './types';

// /gpus and /cpus are the URLs people guess, and they 404ed (U2). Anything
// else in the query (?q=5070) survives the hop; the path decides the category.
export function categoryRedirect(category: Category, search: URLSearchParams): string {
	const params = new URLSearchParams({ category });
	for (const [key, value] of search) {
		if (key !== 'category') params.append(key, value);
	}
	return `/products?${params.toString()}`;
}
