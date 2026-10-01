export type Theme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'trackaroo-theme';

// Page background per theme, used for <meta name="theme-color">. Keep in step
// with --bg in app.css and the inline script in app.html.
export const THEME_COLORS: Record<Theme, string> = { dark: '#0f1117', light: '#f6f7f9' };

export function getInitialTheme(): Theme {
	if (typeof document === 'undefined') return 'dark';
	return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

export function setTheme(theme: Theme): void {
	document.documentElement.dataset.theme = theme;
	document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme]);
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
