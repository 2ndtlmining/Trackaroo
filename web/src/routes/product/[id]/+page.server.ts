import { error } from '@sveltejs/kit';
import { getProductHistory } from '$lib/server/repos';
import { getDb } from '$lib/server/db';

export function load({ params }: { params: { id: string } }) {
	const id = Number(params.id);
	if (!Number.isInteger(id) || id <= 0) {
		error(404, 'Product not found');
	}
	const data = getProductHistory(getDb(), id);
	if (!data) {
		error(404, 'Product not found');
	}
	return data;
}