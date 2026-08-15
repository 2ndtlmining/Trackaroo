export type Theme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'trackaroo-theme';

export function getInitialTheme(): Theme {
	if (typeof document === 'undefined') return 'dark';
	return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

export function setTheme(theme: Theme): void {
	document.documentElement.dataset.theme = theme;
	try {
		localStorage.setItem(THEME_STORAGE_KEY, theme);
	} catch {
		// storage unavailable (private mode) — theme still applies for this session
	}
}

export function toggleTheme(): Theme {
	const next: Theme = getInitialTheme() === 'dark' ? 'light' : 'dark';
	setTheme(next);
	return next;
}
