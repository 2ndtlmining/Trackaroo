// CHANGELOG.md lives at the repo root and is bundled at build time (`?raw`), so
// /changelog never reads the disk. The Dockerfile copies it next to web/.
import md from '../../../../CHANGELOG.md?raw';
import { parseChangelog, type Release } from '$lib/changelog';

const releases: Release[] = parseChangelog(md);

export function getReleases(): Release[] {
	return releases;
}
