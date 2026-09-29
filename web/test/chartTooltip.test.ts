import { describe, expect, it } from 'vitest';
import { renderTooltip } from '../src/lib/chartTooltip';

describe('renderTooltip (#27)', () => {
	it('renders a scraped listing name as text, never as markup (Review Focus 4)', () => {
		const el = document.createElement('div');
		const hostile = '<img src=x onerror=alert(1)> Palit 16GB';
		renderTooltip(el, '5 Sep', [{ label: hostile, value: '$699' }]);
		expect(el.querySelector('img')).toBeNull();
		expect(el.textContent).toContain(hostile);
		expect(el.textContent).toContain('$699');
	});

	it('replaces the previous rows instead of appending', () => {
		const el = document.createElement('div');
		renderTooltip(el, '5 Sep', [{ label: 'A', value: '$1' }]);
		renderTooltip(el, '6 Sep', [{ label: 'B', value: '$2' }]);
		expect(el.textContent).not.toContain('5 Sep');
		expect(el.textContent).toContain('6 Sep');
		expect(el.children).toHaveLength(2); // date header + one row
	});
});
