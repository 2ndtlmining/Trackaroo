// "GeForce RTX 5060 Ti" is the 16GB card, but beside "GeForce RTX 5060 Ti 8GB"
// it reads as the generic one (Phase 1 #2 split memory variants into their own
// products). Where a "<model> <N>GB" sibling exists, the base card shows its
// size too. Display only: products.model in the DB is unchanged.
import type { Category } from './types';

interface Named {
	id: number;
	category: Category;
	model: string;
	vramGb: number | null;
}

const MEMORY_SUFFIX = /\s\d+GB$/i;

export function buildDisplayNames(items: readonly Named[]): Map<number, string> {
	const gpuModels = items.filter((i) => i.category === 'gpu').map((i) => i.model.toLowerCase());
	const names = new Map<number, string>();
	for (const i of items) {
		const prefix = `${i.model.toLowerCase()} `;
		const hasSibling =
			i.category === 'gpu' &&
			i.vramGb !== null &&
			!MEMORY_SUFFIX.test(i.model) &&
			gpuModels.some((m) => m.startsWith(prefix) && /^\d+gb$/.test(m.slice(prefix.length)));
		names.set(i.id, hasSibling ? `${i.model} ${i.vramGb}GB` : i.model);
	}
	return names;
}

export function displayName(names: ReadonlyMap<number, string>, id: number, model: string): string {
	return names.get(id) ?? model;
}
