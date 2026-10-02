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

	it('keeps prose under a release as its intro', () => {
		const [r] = parseChangelog('## 1.0.0 — 2027-01-01\n\nOne release for everything.\n\n- x');
		expect(r.intro).toEqual(['One release for everything.']);
		expect(r.sections).toEqual([{ title: null, items: ['x'] }]);
	});

	it('joins wrapped and indented lines onto the bullet above', () => {
		const [r] = parseChangelog('## 1.0.0\n- first part\n  second part\n  - a sub point\n- next');
		expect(r.sections[0].items).toEqual(['first part second part a sub point', 'next']);
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

	it('never nests markup inside a link', () => {
		expect(renderInline('[see #12](https://a.b/(#12)')).toBe('<a href="https://a.b/(#12">see #12</a>');
		expect(renderInline('[x](https://a.b/**y**)')).toBe('<a href="https://a.b/**y**">x</a>');
	});

	it('cannot break out of the href attribute', () => {
		expect(renderInline('[x](https://a.b/"onmouseover=alert(1))')).toBe(
			'<a href="https://a.b/&quot;onmouseover=alert(1">x</a>)'
		);
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

	it('lists releases newest first', () => {
		const parts = parseChangelog(md).map((r) => r.version.split('.').map(Number));
		for (let i = 1; i < parts.length; i++) {
			const [a, b] = [parts[i - 1], parts[i]];
			expect(a[0] - b[0] || a[1] - b[1] || a[2] - b[2]).toBeGreaterThan(0);
		}
	});
});
