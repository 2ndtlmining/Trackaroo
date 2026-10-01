import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyText } from '$lib/clipboard';

function fakeDom(execResult: boolean | Error) {
	const area = { value: '', style: {}, setAttribute: vi.fn(), select: vi.fn(), remove: vi.fn() };
	const doc = {
		createElement: vi.fn(() => area),
		body: { appendChild: vi.fn() },
		execCommand: vi.fn(() => {
			if (execResult instanceof Error) throw execResult;
			return execResult;
		})
	};
	vi.stubGlobal('document', doc);
	return { area, doc };
}

afterEach(() => vi.unstubAllGlobals());

describe('copyText', () => {
	it('uses the async clipboard when available', async () => {
		const writeText = vi.fn().mockResolvedValue(undefined);
		vi.stubGlobal('navigator', { clipboard: { writeText } });
		expect(await copyText('row')).toBe(true);
		expect(writeText).toHaveBeenCalledWith('row');
	});

	it('falls back to a textarea when navigator.clipboard is undefined (plain http)', async () => {
		vi.stubGlobal('navigator', {});
		const { area, doc } = fakeDom(true);
		expect(await copyText('row')).toBe(true);
		expect(area.value).toBe('row');
		expect(doc.execCommand).toHaveBeenCalledWith('copy');
		expect(area.remove).toHaveBeenCalled();
	});

	it('falls back when writeText throws', async () => {
		vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
		const { doc } = fakeDom(true);
		expect(await copyText('row')).toBe(true);
		expect(doc.execCommand).toHaveBeenCalled();
	});

	it('resolves false when the fallback fails or throws', async () => {
		vi.stubGlobal('navigator', {});
		fakeDom(false);
		expect(await copyText('row')).toBe(false);
		fakeDom(new Error('nope'));
		expect(await copyText('row')).toBe(false);
	});
});
