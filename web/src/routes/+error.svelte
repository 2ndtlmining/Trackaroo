<script lang="ts">
	import { page } from '$app/state';
	import Wordmark from '$lib/components/Wordmark.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import PageHead from '$lib/components/PageHead.svelte';

	/**
	 * Without this, every failure — a 404 from an unknown product id, a 400 from
	 * a malformed /compare URL, or a 500 because trackaroo.db is missing (db.ts
	 * opens with fileMustExist) — rendered SvelteKit's unstyled default page
	 * with no way back into the app.
	 */
	const status = $derived(page.status);
	const heading = $derived(status === 404 ? 'Page not found' : 'Something went wrong');
	const message = $derived(page.error?.message ?? 'Something went wrong.');

	const hint = $derived.by(() => {
		if (status === 404) return 'The page or product you asked for does not exist.';
		if (status === 400) return 'That link looks malformed — check the query parameters.';
		if (/no such file|unable to open database|SQLITE_CANTOPEN/i.test(message))
			return 'The database could not be opened. Run `python seed.py` (and `python run_daily.py` for data), or check that TRACKAROO_DB points at the right file.';
		if (/no such table/i.test(message))
			return 'The database is missing a table. Run `python migrate.py` to bring the schema up to date.';
		if (status >= 500) return 'The server hit an unexpected error. The details are in the server log.';
		return null;
	});
</script>

<PageHead title={heading} description={message} />

<div class="mx-auto max-w-xl py-16 text-center">
	<div class="mb-8"><Wordmark size="large" /></div>
	<PageHeader title={heading} subtitle={message} />

	{#if hint}
		<p class="mt-3 text-sm text-text-muted">{hint}</p>
	{/if}

	<div class="mt-8 flex items-center justify-center gap-3">
		<a
			href={page.url.pathname + page.url.search}
			data-sveltekit-reload
			class="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text no-underline hover:bg-surface-hover hover:no-underline"
		>
			Try again
		</a>
		<a
			href="/"
			class="rounded-md px-3 py-2 text-sm text-text-muted no-underline hover:text-text hover:no-underline"
		>
			Home
		</a>
	</div>
	<p class="num mt-6 text-xs text-text-muted">{status}</p>
</div>
