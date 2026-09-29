// One title format for every page (#25). app.html used to carry a static
// <title> ahead of %sveltekit.head%, so every served page had two and the
// generic one came first -- link unfurls all read the same title.
import { formatAud } from './formats';

export const SITE_NAME = 'Trackaroo';
export const SITE_DESCRIPTION =
	'Daily Australian retail prices for CPUs and GPUs: price history, deals and movers.';

export function pageTitle(title?: string | null): string {
	const t = title?.trim();
	return t ? `${t} · ${SITE_NAME}` : `${SITE_NAME} — AU CPU & GPU price tracker`;
}

export function productPageTitle(
	name: string,
	price: number | null,
	retailerLabel: string | null
): string {
	return pageTitle(
		price !== null && retailerLabel ? `${name} — ${formatAud(price)} at ${retailerLabel}` : name
	);
}
