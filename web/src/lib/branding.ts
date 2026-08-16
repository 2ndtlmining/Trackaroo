// Client-safe brand derivation for AIB GPU variants. Lives outside `$lib/server`
// because it is used by both the server (repos.ts) and client-side components.

export const AIB_BRAND_ALIASES: Record<string, string> = {
	asus: 'ASUS',
	gigabyte: 'Gigabyte',
	msi: 'MSI',
	palit: 'Palit',
	inno3d: 'Inno3D',
	pny: 'PNY',
	evga: 'EVGA',
	zotac: 'ZOTAC',
	galax: 'GALAX',
	sapphire: 'Sapphire',
	powercolor: 'PowerColor',
	xfx: 'XFX',
	kfa2: 'KFA2',
	gainward: 'Gainward',
	manli: 'Manli',
	colorful: 'Colorful',
	yeston: 'Yeston',
	maxsun: 'MaxSun',
	leadtek: 'Leadtek',
	nvidia: 'NVIDIA',
	amd: 'AMD',
	intel: 'Intel'
};

// Maps the first token of a retailer variant name (e.g. "Gigabyte GeForce RTX
// 5060 ...") to a canonical brand. Falls back to the product brand when the
// prefix is unknown or absent (e.g. CPU listings named "Ryzen 5 7600, Tray").
export function deriveListingBrand(
	variantName: string | null,
	productBrand: string
): string {
	if (!variantName) return productBrand;
	const first = variantName.trim().split(/[\s,]+/)[0].toLowerCase();
	return AIB_BRAND_ALIASES[first] ?? productBrand;
}