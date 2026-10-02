import { describe, expect, it } from 'vitest';
import {
	GST,
	MSRP_TONE_CLASS,
	formatMsrpDelta,
	isBelowMsrp,
	msrpAud,
	msrpDelta,
	msrpExplanation,
	msrpPhrase,
	msrpTone
} from '../src/lib/msrp';
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

describe('msrp presentation (Task 3)', () => {
	it('tones: under at -2% or less, near within 2%, over at +2% or more', () => {
		expect(msrpTone(-0.03)).toBe('under');
		expect(msrpTone(-0.02)).toBe('under');
		expect(msrpTone(-0.019)).toBe('near');
		expect(msrpTone(0)).toBe('near');
		expect(msrpTone(0.019)).toBe('near');
		expect(msrpTone(0.02)).toBe('over');
		expect(MSRP_TONE_CLASS).toEqual({ under: 'text-success', near: 'text-text-muted', over: 'text-warning' });
	});
	it('formats a signed whole percent, "–" when unknown', () => {
		expect(formatMsrpDelta(-0.034)).toBe('−3%');
		expect(formatMsrpDelta(0.12)).toBe('+12%');
		expect(formatMsrpDelta(0.004)).toBe('0%');
		expect(formatMsrpDelta(-0.004)).toBe('0%');
		expect(formatMsrpDelta(null)).toBe('–');
	});
	it('phrases the line in words', () => {
		expect(msrpPhrase(-0.034)).toBe('3% under US launch MSRP');
		expect(msrpPhrase(0.12)).toBe('12% over US launch MSRP');
		expect(msrpPhrase(0.004)).toBe('At US launch MSRP');
	});
	it('isBelowMsrp needs every input and a negative delta', () => {
		expect(isBelowMsrp(100, 399, fx(1.5))).toBe(true);
		// Agrees with the display: -0.3% shows "0%", so it is not "below".
		expect(isBelowMsrp(657, 399, fx(1.5))).toBe(false);
		expect(formatMsrpDelta(msrpDelta(657, msrpAud(399, fx(1.5))))).toBe('0%');
		expect(isBelowMsrp(650, 399, fx(1.5))).toBe(true);
		expect(isBelowMsrp(500, 279, fx(1.5))).toBe(false);
		expect(isBelowMsrp(100, null, fx(1.5))).toBe(false);
		expect(isBelowMsrp(100, 399, null)).toBe(false);
		expect(isBelowMsrp(null, 399, fx(1.5))).toBe(false);
	});
});
