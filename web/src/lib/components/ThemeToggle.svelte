<script lang="ts">
	import { getInitialTheme, setTheme, type Theme } from '$lib/theme';

	let theme: Theme = $state(getInitialTheme());

	function toggle() {
		theme = theme === 'dark' ? 'light' : 'dark';
		setTheme(theme);
	}
</script>

<button
	type="button"
	onclick={toggle}
	aria-label="Switch to {theme === 'dark' ? 'light' : 'dark'} mode"
	class="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface text-text-muted hover:bg-surface-hover hover:text-text"
>
	{#if theme === 'dark'}
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
			<circle cx="12" cy="12" r="4"></circle>
			<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path>
		</svg>
	{:else}
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
		</svg>
	{/if}
</button>
