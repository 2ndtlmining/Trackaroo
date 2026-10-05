import type { TierLabels } from '../../src/lib/models';

// Today's five lines, as db/generations.toml seeds them into the table.
export const LABELS: TierLabels = {
	'amd-cpu': { current: 'Ryzen 9000 (Zen 5)', 'current-1': 'Ryzen 7000 (Zen 4)', 'current-2': 'Ryzen 5000 (Zen 3)' },
	'intel-cpu': { current: 'Core Ultra 200 (Arrow Lake)', 'current-1': 'Core 14th Gen', 'current-2': 'Core 13th Gen' },
	'nvidia-gpu': { current: 'RTX 50 (Blackwell)', 'current-1': 'RTX 40 (Ada)', 'current-2': 'RTX 30 (Ampere)' },
	'amd-gpu': { current: 'RX 9000 (RDNA 4)', 'current-1': 'RX 7000 (RDNA 3)', 'current-2': 'RX 6000 (RDNA 2)' },
	'intel-gpu': { current: 'Arc B (Battlemage)', 'current-1': 'Arc A (Alchemist)' }
};
