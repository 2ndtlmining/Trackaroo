import { describe, expect, it } from 'vitest';
import { parseChangelog, renderInline } from '../src/lib/changelog';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SAMPLE = `# Changelog

Intro text that is not a release.

## Unreleased

### Added
- Something not shipped yet

## 0.4.0 — 2026-10-03

### Added
- Buying signals (#31)
- MSRP in today's AUD (#32)

### Fixed
- A bug

## 0.3.0 — 2026-10-02

- Plain bullet with no section
`;

describe('parseChangelog', () => {
	it('returns released versions newest first, skipping Unreleased', () => {
		const releases = parseChangelog(SAMPLE);
		expect(releases.map((r) => r.version)).toEqual(['0.4.0', '0.3.0']);
		expect(releases[0].date).toBe('2026-10-03');
	});

	it('groups bullets under their section', () => {
		const [latest] = parseChangelog(SAMPLE);
		expect(latest.sections).toEqual([
			{ title: 'Added', items: ['Buying signals (#31)', "MSRP in today's AUD (#32)"] },
			{ title: 'Fixed', items: ['A bug'] }
		]);
	});

	it('keeps bullets that have no section heading', () => {
		const releases = parseChangelog(SAMPLE);
		expect(releases[1].sections).toEqual([{ title: null, items: ['Plain bullet with no section'] }]);
	});

	it('accepts a plain hyphen between version and date', () => {
		expect(parseChangelog('## 1.2.3 - 2027-01-05\n- x')[0]).toMatchObject({
			version: '1.2.3',
			date: '2027-01-05'
		});
	});

	it('returns [] for an empty file', () => {
		expect(parseChangelog('')).toEqual([]);
	});
});

describe('renderInline', () => {
	it('escapes HTML', () => {
		expect(renderInline('<script>&"')).toBe('&lt;script&gt;&amp;&quot;');
	});

	it('renders code, bold and issue links', () => {
		expect(renderInline('`fx.py` is **new** (#32)')).toBe(
			'<code>fx.py</code> is <strong>new</strong> (<a href="https://github.com/2ndtlmining/Trackaroo/issues/32">#32</a>)'
		);
	});

	it('renders http(s) links and refuses other schemes', () => {
		expect(renderInline('[RBA](https://www.rba.gov.au/)')).toBe(
			'<a href="https://www.rba.gov.au/">RBA</a>'
		);
		expect(renderInline('[x](javascript:alert(1))')).toBe('[x](javascript:alert(1))');
	});

	it('does not link issue numbers inside code', () => {
		expect(renderInline('`#12`')).toBe('<code>#12</code>');
	});
});

// vitest runs from web/.
describe('the repo CHANGELOG.md', () => {
	const md = readFileSync(resolve('..', 'CHANGELOG.md'), 'utf8');
	const pkg = JSON.parse(readFileSync(resolve('package.json'), 'utf8'));

	it('its newest release matches web/package.json version', () => {
		expect(parseChangelog(md)[0]?.version).toBe(pkg.version);
	});
});
