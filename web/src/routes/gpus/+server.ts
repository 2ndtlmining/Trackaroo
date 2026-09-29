import { redirect } from '@sveltejs/kit';
import { categoryRedirect } from '$lib/legacyRoutes';

export function GET({ url }: { url: URL }) {
	redirect(301, categoryRedirect('gpu', url.searchParams));
}
