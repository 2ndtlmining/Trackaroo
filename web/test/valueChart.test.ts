import { describe, expect, it } from 'vitest';
import { audTick, gapLabel, logScale, niceRange, niceScale, shortName, stepPath, kiloLabel } from '../src/lib/valueChart';
import { metricsFor, parseMetric, sourceCitation, sourceNote } from '../src/lib/perfIndex';

describe('niceScale (#33 /value axes)', () => {
	it('rounds the top up to a clean step and lists ticks from 0', () => {
		expect(niceScale(7199)).toEqual({
			max: 8000,
			ticks: [0, 2000, 4000, 6000, 8000]
		});
		expect(niceScale(87)).toEqual({
			max: 100,
			ticks: [0, 20, 40, 60, 80, 100]
		});
	});
	it('handles 2.5 and 5 steps', () => {
		expect(niceScale(1149).ticks).toEqual([0, 250, 500, 750, 1000, 1250]);
		expect(niceScale(46).max).toBe(50);
	});
	it('never divides by zero on empty or non-positive data', () => {
		const s = niceScale(0);
		expect(s.max).toBeGreaterThan(0);
		expect(s.ticks[0]).toBe(0);
		expect(niceScale(Number.NaN).max).toBeGreaterThan(0);
	});
});

describe('niceRange (performance axis)', () => {
	it('starts at 0 when the data spreads widely', () => {
		expect(niceRange(15, 93)).toEqual({ lo: 0, hi: 100, ticks: [0, 20, 40, 60, 80, 100] });
	});
	it('zooms in on a tight cluster, never putting a point on the floor', () => {
		expect(niceRange(89.2, 112.7)).toEqual({ lo: 85, hi: 115, ticks: [85, 90, 95, 100, 105, 110, 115] });
		expect(niceRange(90, 110).lo).toBeLessThan(90);
	});
	it('copes with one point', () => {
		const r = niceRange(100, 100);
		expect(r.lo).toBeLessThan(100);
		expect(r.hi).toBeGreaterThanOrEqual(100);
	});
});

describe('logScale (price axis)', () => {
	it('pads the range and ticks 1-2-5 across decades', () => {
		const s = logScale(229, 7199);
		expect(s.lo).toBeLessThan(229);
		expect(s.hi).toBeGreaterThan(7199);
		expect(s.ticks).toEqual([200, 500, 1000, 2000, 5000]);
	});
	it('ticks finer inside one decade', () => {
		expect(logScale(189, 1199).ticks).toEqual([200, 300, 400, 500, 700, 1000]);
	});
	it('survives one point or bad input', () => {
		expect(logScale(500, 500).ticks).toEqual([500]);
		const s = logScale(Number.NaN, 0);
		expect(s.lo).toBeGreaterThan(0);
		expect(s.hi).toBeGreaterThan(s.lo);
	});
});

describe('stepPath', () => {
	it('is empty for no points and a bare move for one', () => {
		expect(stepPath([])).toBe('');
		expect(stepPath([{ x: 1, y: 2 }])).toBe('M1,2');
	});
	it('steps across to the next price, then up to its performance', () => {
		expect(
			stepPath([
				{ x: 10, y: 90 },
				{ x: 40, y: 50 },
				{ x: 70, y: 20 }
			])
		).toBe('M10,90H40V50H70V20');
	});
});

describe('labels', () => {
	it('shortens GPU family prefixes and leaves CPUs alone', () => {
		expect(shortName('GeForce RTX 5060 Ti 16GB')).toBe('RTX 5060 Ti 16GB');
		expect(shortName('Radeon RX 7800 XT')).toBe('RX 7800 XT');
		expect(shortName('Ryzen 7 9800X3D')).toBe('Ryzen 7 9800X3D');
	});
	it('states the gap to the runner-up, or nothing without one', () => {
		expect(gapLabel(0.123)).toBe('12% faster than the runner-up');
		expect(gapLabel(0)).toBe('Level with the runner-up');
		expect(gapLabel(0.001)).toBe('Level with the runner-up');
		expect(gapLabel(null)).toBeNull();
	});
	it('keeps price ticks short', () => {
		expect([0, 250, 1000, 1250, 8000].map(audTick)).toEqual(['$0', '$250', '$1k', '$1.25k', '$8k']);
	});
	it('prints perf per A$1k as a whole number', () => {
		expect(kiloLabel(52.6)).toBe('53');
		expect(kiloLabel(null)).toBe('–');
	});
});

describe('metric options', () => {
	it('offers raster and RT for GPUs, gaming only for CPUs', () => {
		expect(metricsFor('gpu')).toEqual(['gpu_raster_1440p', 'gpu_rt_1440p']);
		expect(metricsFor('cpu')).toEqual(['cpu_gaming_1080p']);
	});
	it('falls back to the category default for a missing or foreign metric', () => {
		expect(parseMetric('gpu', 'gpu_rt_1440p')).toBe('gpu_rt_1440p');
		expect(parseMetric('gpu', 'cpu_gaming_1080p')).toBe('gpu_raster_1440p');
		expect(parseMetric('cpu', 'gpu_rt_1440p')).toBe('cpu_gaming_1080p');
		expect(parseMetric('cpu', null)).toBe('cpu_gaming_1080p');
		expect(parseMetric('gpu', 'junk')).toBe('gpu_raster_1440p');
	});
	it('cites the source without the metric label', () => {
		expect(sourceCitation('gpu_raster_1440p')).toMatch(/^TechPowerUp, .+, Apr 2026$/);
		expect(sourceNote('gpu_raster_1440p')).toBe(`1440p raster, ${sourceCitation('gpu_raster_1440p')}`);
	});
});
