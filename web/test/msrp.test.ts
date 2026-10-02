import { describe, expect, it } from 'vitest';
import { GST, msrpAud, msrpDelta, msrpExplanation } from '../src/lib/msrp';
import type { FxRate } from '../src/lib/models';

const fx = (audPerUsd: number, source = 'rba', rateDate = '2026-10-01'): FxRate => ({ rateDate, audPerUsd, source });

describe('msrpAud', () => {
	it('is USD x rate x (1 + GST)', () => {
		expect(GST).toBe(0.1);
		expect(msrpAud(1099, fx(1.5))).toBeCloseTo(1813.35, 2);
	});
	it('is null without a rate or an MSRP', () => {
		expect(msrpAud(1099, null)).toBeNull();
		expect(msrpAud(null, fx(1.5))).toBeNull();
	});
	it('is null for zero or negative inputs', () => {
		expect(msrpAud(0, fx(1.5))).toBeNull();
		expect(msrpAud(-5, fx(1.5))).toBeNull();
		expect(msrpAud(1099, fx(0))).toBeNull();
		expect(msrpAud(1099, fx(-1.5))).toBeNull();
	});
});

describe('msrpDelta', () => {
	it('is a fraction, negative when under MSRP', () => {
		expect(msrpDelta(970, 1000)).toBeCloseTo(-0.03, 10);
		expect(msrpDelta(1120, 1000)).toBeCloseTo(0.12, 10);
		expect(msrpDelta(1000, 1000)).toBe(0);
	});
	it('is null with a missing, zero or negative input', () => {
		expect(msrpDelta(null, 1000)).toBeNull();
		expect(msrpDelta(900, null)).toBeNull();
		expect(msrpDelta(900, 0)).toBeNull();
		expect(msrpDelta(0, 1000)).toBeNull();
		expect(msrpDelta(-1, 1000)).toBeNull();
		expect(msrpDelta(900, -1000)).toBeNull();
	});
});

describe('msrpExplanation', () => {
	it('spells out the sum with source and date', () => {
		expect(msrpExplanation(1099, fx(1.5432))).toBe('US$1,099 × 1.5432 AUD/USD (RBA, 1 Oct 2026) + 10% GST');
	});
	it('maps frankfurter to ECB and shows unknown sources raw', () => {
		expect(msrpExplanation(1099, fx(1.5, 'frankfurter'))).toContain('(ECB, 1 Oct 2026)');
		expect(msrpExplanation(1099, fx(1.5, 'mystery'))).toContain('(mystery, 1 Oct 2026)');
	});
});
