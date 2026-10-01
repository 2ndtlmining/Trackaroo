import { browser } from '$app/environment';
import { page } from '$app/state';

// The current query string for pages that keep client state in the URL (#26).
// In the browser the address bar is the truth, not page.url: replaceState
// leaves page.url alone, and SvelteKit's popstate navigates Back to the URL
// the page was *loaded* with, dropping the shallow parameters. By the time a
// component mounts or its effects re-run, `location` already holds the target
// URL (SvelteKit pushes history before it renders). page.url only in SSR.
export function urlParams(): URLSearchParams {
	return browser ? new URLSearchParams(location.search) : page.url.searchParams;
}
