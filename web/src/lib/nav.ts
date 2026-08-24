// Nav links and active-state matching. Pure and separate from Header.svelte
// because matching has to consider the query string, not just the pathname:
// GPUs and CPUs are both /products, distinguished only by ?category=.
export interface NavLink {
	href: string;
	label: string;
}

// Deals first — the site's purpose gets the first slot. GPUs/CPUs replace
// Products so a category is a place rather than a filter re-applied on every
// page. Compare joins the nav, ending its orphan status (spec §6).
export const NAV_LINKS: NavLink[] = [
	{ href: '/deals', label: 'Deals' },
	{ href: '/products?category=gpu', label: 'GPUs' },
	{ href: '/products?category=cpu', label: 'CPUs' },
	{ href: '/movers', label: 'Movers' },
	{ href: '/compare', label: 'Compare' }
];

export function isActiveLink(href: string, pathname: string, search: URLSearchParams): boolean {
	const [linkPath, linkQuery] = href.split('?');
	if (linkPath !== pathname) return false;
	if (!linkQuery) return true;
	// Every parameter the link pins must match; anything else in the URL
	// (sort, page, search terms) is irrelevant to which place we are in.
	for (const [key, value] of new URLSearchParams(linkQuery)) {
		if (search.get(key) !== value) return false;
	}
	return true;
}
