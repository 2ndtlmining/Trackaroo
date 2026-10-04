import { describe, expect, it } from 'vitest';
import { findRival, matchupLines, type MatchupCandidate } from '../src/lib/matchups';

function gpu(
	id: number,
	brand: string,
	raster: number | null,
	o: { vram?: number | null; price?: number | null; tier?: string | null; rt?: number | null } = {}
): MatchupCandidate {
	const scores: MatchupCandidate['scores'] = {};
	if (raster !== null) scores.gpu_raster_1440p = raster;
	if (o.rt !== undefined && o.rt !== null) scores.gpu_rt_1440p = o.rt;
	else if (o.rt === undefined && raster !== null) scores.gpu_rt_1440p = raster;
	return {
		id,
		brand,
		model: `G${id}`,
		vramGb: o.vram === undefined ? 16 : o.vram,
		tier: o.tier === undefined ? 'current' : o.tier,
		price: o.price === undefined ? 1000 : o.price,
		scores
	};
}

function cpu(id: number, brand: string, score: number | null, price: number | null = 500): MatchupCandidate {
	return {
		id,
		brand,
		model: `C${id}`,
		vramGb: null,
		tier: 'current',
		price,
		scores: score === null ? {} : { cpu_gaming_1080p: score }
	};
}

describe('findRival', () => {
	it('picks the nearest other-brand GPU', () => {
		const p = gpu(1, 'NVIDIA', 40);
		const pool = [p, gpu(2, 'AMD', 44), gpu(3, 'AMD', 41), gpu(4, 'NVIDIA', 40)];
		expect(findRival(p, pool, 'gpu')?.id).toBe(3);
	});

	it('pairs AMD GPUs with NVIDIA too', () => {
		const p = gpu(1, 'AMD', 40);
		expect(findRival(p, [p, gpu(2, 'NVIDIA', 39)], 'gpu')?.id).toBe(2);
	});

	it('never matches Intel GPUs, either way', () => {
		const intel = gpu(1, 'Intel', 40);
		expect(findRival(intel, [intel, gpu(2, 'AMD', 40), gpu(3, 'NVIDIA', 40)], 'gpu')).toBeNull();
		const p = gpu(4, 'NVIDIA', 40);
		expect(findRival(p, [p, intel], 'gpu')).toBeNull();
	});

	it('pairs Intel and AMD CPUs both ways', () => {
		const intel = cpu(1, 'Intel', 80);
		const amd = cpu(2, 'AMD', 82);
		expect(findRival(intel, [intel, amd], 'cpu')?.id).toBe(2);
		expect(findRival(amd, [intel, amd], 'cpu')?.id).toBe(1);
	});

	it('accepts a gap of exactly 15% and rejects anything over', () => {
		const p = gpu(1, 'NVIDIA', 40);
		expect(findRival(p, [p, gpu(2, 'AMD', 46)], 'gpu')?.id).toBe(2);
		expect(findRival(p, [p, gpu(2, 'AMD', 34)], 'gpu')?.id).toBe(2);
		expect(findRival(p, [p, gpu(2, 'AMD', 46.1)], 'gpu')).toBeNull();
		expect(findRival(p, [p, gpu(2, 'AMD', 33.9)], 'gpu')).toBeNull();
	});

	it('only considers current and current-1 rivals', () => {
		const p = gpu(1, 'NVIDIA', 40);
		expect(findRival(p, [p, gpu(2, 'AMD', 40, { tier: 'current-2' })], 'gpu')).toBeNull();
		expect(findRival(p, [p, gpu(2, 'AMD', 40, { tier: null })], 'gpu')).toBeNull();
		expect(findRival(p, [p, gpu(2, 'AMD', 40, { tier: 'current-1' })], 'gpu')?.id).toBe(2);
	});

	it('lets P itself be any tier', () => {
		const p = gpu(1, 'NVIDIA', 40, { tier: 'current-2' });
		expect(findRival(p, [p, gpu(2, 'AMD', 40)], 'gpu')?.id).toBe(2);
	});

	it('needs P and the rival in stock with a positive price', () => {
		const p = gpu(1, 'NVIDIA', 40);
		expect(findRival(p, [p, gpu(2, 'AMD', 40, { price: null })], 'gpu')).toBeNull();
		expect(findRival(p, [p, gpu(2, 'AMD', 40, { price: 0 })], 'gpu')).toBeNull();
		const unpriced = gpu(3, 'NVIDIA', 40, { price: null });
		expect(findRival(unpriced, [unpriced, gpu(2, 'AMD', 40)], 'gpu')).toBeNull();
	});

	it('needs a main-metric score on both sides', () => {
		const p = gpu(1, 'NVIDIA', 40);
		expect(findRival(p, [p, gpu(2, 'AMD', null)], 'gpu')).toBeNull();
		const unscored = gpu(3, 'NVIDIA', null);
		expect(findRival(unscored, [unscored, gpu(2, 'AMD', 40)], 'gpu')).toBeNull();
	});

	it('prefers the same VRAM inside the 3-point window', () => {
		const p = gpu(1, 'NVIDIA', 40, { vram: 16 });
		const near8 = gpu(2, 'AMD', 40, { vram: 8 });
		const same16 = gpu(3, 'AMD', 43, { vram: 16 });
		expect(findRival(p, [p, near8, same16], 'gpu')?.id).toBe(3);
	});

	it('keeps the nearest card when the same-VRAM one is outside the window', () => {
		const p = gpu(1, 'NVIDIA', 40, { vram: 16 });
		const near8 = gpu(2, 'AMD', 40, { vram: 8 });
		const same16 = gpu(3, 'AMD', 43.5, { vram: 16 });
		expect(findRival(p, [p, near8, same16], 'gpu')?.id).toBe(2);
	});

	it('breaks an exact tie by VRAM before price', () => {
		const p = gpu(1, 'AMD', 33, { vram: 16 });
		const cheap8 = gpu(2, 'NVIDIA', 35, { vram: 8, price: 520 });
		const dear16 = gpu(3, 'NVIDIA', 35, { vram: 16, price: 600 });
		expect(findRival(p, [p, cheap8, dear16], 'gpu')?.id).toBe(3);
	});

	it('breaks a remaining tie on lower price, then lower id', () => {
		const p = gpu(1, 'NVIDIA', 40);
		expect(findRival(p, [p, gpu(5, 'AMD', 41, { price: 900 }), gpu(4, 'AMD', 41, { price: 800 })], 'gpu')?.id).toBe(4);
		expect(findRival(p, [p, gpu(5, 'AMD', 41), gpu(4, 'AMD', 41)], 'gpu')?.id).toBe(4);
	});

	it('skips the VRAM tie-break for CPUs', () => {
		const p = cpu(1, 'Intel', 80);
		expect(findRival(p, [p, cpu(2, 'AMD', 81), cpu(3, 'AMD', 83)], 'cpu')?.id).toBe(2);
	});
});

describe('matchupLines', () => {
	const rival = gpu(2, 'AMD', 100, { price: 100, rt: 100 });

	it('says cheaper below 0.98 and rounds the percentage', () => {
		const p = gpu(1, 'NVIDIA', 100, { price: 97, rt: 100 });
		expect(matchupLines(p, rival, 'gpu')[0]).toEqual({ metric: 'gpu_raster_1440p', direction: 'cheaper', pct: 3 });
	});

	it('treats exactly 0.98 and exactly 1.02 as about the same', () => {
		expect(matchupLines(gpu(1, 'NVIDIA', 100, { price: 98 }), rival, 'gpu')[0].direction).toBe('same');
		expect(matchupLines(gpu(1, 'NVIDIA', 100, { price: 102 }), rival, 'gpu')[0].direction).toBe('same');
	});

	it('says dearer above 1.02', () => {
		const p = gpu(1, 'NVIDIA', 100, { price: 103, rt: 100 });
		expect(matchupLines(p, rival, 'gpu')[0]).toEqual({ metric: 'gpu_raster_1440p', direction: 'dearer', pct: 3 });
	});

	it('gives ray tracing its own line, even when it points the other way', () => {
		const p = gpu(1, 'NVIDIA', 35, { price: 520, rt: 25 });
		const r = gpu(2, 'AMD', 33, { price: 650, rt: 33 });
		expect(matchupLines(p, r, 'gpu')).toEqual([
			{ metric: 'gpu_raster_1440p', direction: 'cheaper', pct: 25 },
			{ metric: 'gpu_rt_1440p', direction: 'dearer', pct: 6 }
		]);
	});

	it('leaves out ray tracing when either side has no RT score', () => {
		const p = gpu(1, 'NVIDIA', 100, { price: 90, rt: null });
		expect(matchupLines(p, rival, 'gpu').map((l) => l.metric)).toEqual(['gpu_raster_1440p']);
		const r = gpu(3, 'AMD', 100, { price: 100, rt: null });
		expect(matchupLines(gpu(1, 'NVIDIA', 100, { price: 90 }), r, 'gpu').map((l) => l.metric)).toEqual([
			'gpu_raster_1440p'
		]);
	});

	it('gives CPUs one line on 1080p gaming', () => {
		expect(matchupLines(cpu(1, 'Intel', 80, 400), cpu(2, 'AMD', 80, 500), 'cpu')).toEqual([
			{ metric: 'cpu_gaming_1080p', direction: 'cheaper', pct: 20 }
		]);
	});
});
