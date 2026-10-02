import { afterEach, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { buildVersion, releaseVersion } from '../src/lib/server/version';

describe('releaseVersion', () => {
	it('is web/package.json version, baked in at build time', () => {
		const pkg = JSON.parse(readFileSync(resolve('package.json'), 'utf8'));
		expect(releaseVersion()).toBe(pkg.version);
	});
});

describe('buildVersion (#3)', () => {
	afterEach(() => {
		delete process.env.TRACKAROO_VERSION;
	});

	it('is the SHA baked in at build time', () => {
		process.env.TRACKAROO_VERSION = 'abc1234';
		expect(buildVersion()).toBe('abc1234');
	});

	it('is "dev" when unset or blank', () => {
		expect(buildVersion()).toBe('dev');
		process.env.TRACKAROO_VERSION = '  ';
		expect(buildVersion()).toBe('dev');
	});
});
