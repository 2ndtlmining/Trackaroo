import { afterEach, describe, expect, it } from 'vitest';
import { THEME_STORAGE_KEY, getInitialTheme, setTheme, toggleTheme } from '../src/lib/theme';

function setDatasetTheme(theme: string | undefined) {
	if (theme === undefined) delete document.documentElement.dataset.theme;
	else document.documentElement.dataset.theme = theme;
}

afterEach(() => {
	localStorage.clear();
	setDatasetTheme(undefined);
});

describe('getInitialTheme', () => {
	it('defaults to dark when no data-theme attribute is set', () => {
		expect(getInitialTheme()).toBe('dark');
	});

	it('reads light from the data-theme attribute', () => {
		setDatasetTheme('light');
		expect(getInitialTheme()).toBe('light');
	});

	it('falls back to dark for unrecognized values', () => {
		setDatasetTheme('sepia');
		expect(getInitialTheme()).toBe('dark');
	});
});

describe('setTheme', () => {
	it('sets the data-theme attribute and persists to localStorage', () => {
		setTheme('light');
		expect(document.documentElement.dataset.theme).toBe('light');
		expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
	});

	it('does not throw when localStorage is unavailable', () => {
		const original = Object.getOwnPropertyDescriptor(Storage.prototype, 'setItem');
		Object.defineProperty(Storage.prototype, 'setItem', {
			value: () => {
				throw new Error('quota exceeded');
			},
			configurable: true
		});
		try {
			expect(() => setTheme('light')).not.toThrow();
			expect(document.documentElement.dataset.theme).toBe('light');
		} finally {
			if (original) Object.defineProperty(Storage.prototype, 'setItem', original);
		}
	});
});

describe('toggleTheme', () => {
	it('toggles dark to light', () => {
		setDatasetTheme('dark');
		expect(toggleTheme()).toBe('light');
		expect(document.documentElement.dataset.theme).toBe('light');
	});

	it('toggles light to dark', () => {
		setDatasetTheme('light');
		expect(toggleTheme()).toBe('dark');
		expect(document.documentElement.dataset.theme).toBe('dark');
	});
});
