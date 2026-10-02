import { getReleases } from '$lib/server/changelog';

export function load() {
	return { releases: getReleases() };
}
