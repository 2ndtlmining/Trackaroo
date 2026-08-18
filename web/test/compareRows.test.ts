import { describe, expect, it } from 'vitest';
import { buildCompareRows } from '../src/lib/compareRows';
import type { CompareEntry, ComparePrice } from '../src/lib/server/repos';
import type { ProductRow, SpecRow } from '../src/lib/server/db';

function gpuSpec(overrides: Partial<SpecRow> = {}): SpecRow {
	return {
		spec_id: 1,
		product_id: 1,
		source: 'rightnow-gpu-db',
		source_record_key: 'RTX 5060 Ti',
		category: 'gpu',
		architecture: 'Blackwell',
		generation: 'RTX 50',
		launch_date: '2025-04-16',
		launch_msrp_usd: 299,
		vram_gb: 16,
		memory_bus_width_bit: 128,
		memory_type: 'GDDR7',
		tdp_watts: 180,
		core_count: null,
		thread_count: null,
		base_clock_mhz: 2300,
		boost_clock_mhz: 2500,
		socket: null,
		cache_l3_mb: null,
		gpu_die: 'GB206',
		bus_interface: 'PCIe 5.0 x16',
		memory_bandwidth_gbps: 448,
		memory_clock_mhz: 1750,
		process_nm: 5,
		foundry: 'TSMC',
		codename: null,
		l1_cache_kb: null,
		l2_cache_mb: 48,
		memory_speed_mhz: null,
		memory_channels: null,
		memory_types: null,
		integrated_graphics: null,
		raw_json: '{}',
		last_synced_at: '2026-08-15T00:00:00Z',
		...overrides
	};
}

function cpuSpec(overrides: Partial<SpecRow> = {}): SpecRow {
	return {
		spec_id: 2,
		product_id: 2,
		source: 'intel-processors-csv',
		source_record_key: 'Core Ultra 5 245',
		category: 'cpu',
		architecture: 'Arrow Lake',
		generation: 'Core Ultra 200S',
		launch_date: '2025-12-04',
		launch_msrp_usd: 309,
		vram_gb: null,
		memory_bus_width_bit: null,
		memory_type: null,
		tdp_watts: 45,
		core_count: 10,
		thread_count: 10,
		base_clock_mhz: 2500,
		boost_clock_mhz: 4800,
		socket: 'LGA1851',
		cache_l3_mb: 24,
		gpu_die: null,
		bus_interface: null,
		memory_bandwidth_gbps: null,
		memory_clock_mhz: null,
		process_nm: 3,
		foundry: null,
		codename: 'Arrow Lake',
		l1_cache_kb: null,
		l2_cache_mb: null,
		memory_speed_mhz: 6400,
		memory_channels: 2,
		memory_types: 'Up to DDR5 6400 MT/s',
		integrated_graphics: 'Intel Graphics',
		raw_json: '{}',
		last_synced_at: '2026-08-15T00:00:00Z',
		...overrides
	};
}

function entry(overrides: Partial<CompareEntry> = {}): CompareEntry {
	const product: ProductRow = {
		id: 1,
		category: 'gpu',
		brand: 'NVIDIA',
		model: 'RTX 5060 Ti',
		variant: null,
		vram_gb: null,
		cores: null,
		generation_tier: 'current',
		tracked: 1,
		last_snapshot_at: null,
		created_at: '2026-08-09'
	};
	const prices: ComparePrice[] = [{ retailer: 'scorptec', price: 849 }];
	return {
		product,
		spec: gpuSpec(),
		prices,
		cheapestInStock: { price: 849, retailer: 'scorptec' },
		...overrides
	};
}

describe('buildCompareRows', () => {
	it('shows GPU rows for a GPU comparison and hides CPU-only fields', () => {
		const rows = buildCompareRows([entry()]);
		const labels = rows.map((r) => r.label);
		for (const expected of [
			'Best price — scorptec',
			'Cheapest in stock',
			'Launch MSRP (USD)',
			'Architecture',
			'GPU die',
			'VRAM',
			'Memory type',
			'Memory bus',
			'Bandwidth',
			'Bus interface',
			'Process',
			'L2 cache',
			'Base clock',
			'Boost clock',
			'TDP'
		]) {
			expect(labels).toContain(expected);
		}
		for (const absent of ['Cores / shaders', 'Threads', 'Socket', 'L3 cache', 'Codename', 'Memory support']) {
			expect(labels).not.toContain(absent);
		}
	});

	it('shows CPU rows for a CPU comparison and hides GPU-only fields', () => {
		const rows = buildCompareRows([
			entry({
				product: { ...entry().product, id: 2, category: 'cpu', brand: 'Intel', model: 'Core Ultra 5 245' },
				spec: cpuSpec()
			})
		]);
		const labels = rows.map((r) => r.label);
		for (const expected of [
			'Cores / shaders',
			'Threads',
			'Codename',
			'Socket',
			'L3 cache',
			'L2 cache',
			'Memory support',
			'Max memory speed',
			'Base clock',
			'Boost clock',
			'TDP'
		]) {
			expect(labels).toContain(expected);
		}
		for (const absent of ['VRAM', 'Memory type', 'Memory bus', 'Bandwidth', 'Bus interface']) {
			expect(labels).not.toContain(absent);
		}
	});

	it('formats prices, MSRP, clocks and memory through the row value functions', () => {
		const rows = buildCompareRows([entry()]);
		const byLabel = new Map(rows.map((r) => [r.label, r.value]));
		const e = entry();
		expect(byLabel.get('Best price — scorptec')!(e)).toContain('849');
		expect(byLabel.get('Cheapest in stock')!(e)).toContain('849');
		expect(byLabel.get('Launch MSRP (USD)')!(e)).toContain('299');
		expect(byLabel.get('VRAM')!(e)).toBe('16GB');
		expect(byLabel.get('Memory bus')!(e)).toBe('128-bit');
		expect(byLabel.get('Base clock')!(e)).toBe('2.3 GHz');
		expect(byLabel.get('GPU die')!(e)).toBe('GB206');
		expect(byLabel.get('Bandwidth')!(e)).toBe('448 GB/s');
		expect(byLabel.get('Process')!(e)).toBe('TSMC 5 nm');
	});

	it('returns null for fields missing from the spec', () => {
		const rows = buildCompareRows([entry({ spec: gpuSpec({ memory_type: null, tdp_watts: null }) })]);
		const byLabel = new Map(rows.map((r) => [r.label, r.value]));
		const e = entry({ spec: gpuSpec({ memory_type: null, tdp_watts: null }) });
		expect(byLabel.get('Memory type')!(e)).toBeNull();
		expect(byLabel.get('TDP')!(e)).toBeNull();
	});

	it('falls back to architecture when generation is missing (Intel source)', () => {
		const rows = buildCompareRows([
			entry({ spec: gpuSpec({ generation: null, architecture: 'Arrow Lake' }) })
		]);
		const byLabel = new Map(rows.map((r) => [r.label, r.value]));
		const e = entry({ spec: gpuSpec({ generation: null, architecture: 'Arrow Lake' }) });
		expect(byLabel.get('Generation')!(e)).toBe('Arrow Lake');
	});

	it('only emits a Best price row per retailer present in the data', () => {
		const rows = buildCompareRows([entry({ prices: [{ retailer: 'scorptec', price: 849 }] })]);
		const labels = rows.map((r) => r.label);
		expect(labels).toContain('Best price — scorptec');
		expect(labels).not.toContain('Best price — pccg');
	});
});