<script lang="ts">
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import PageHead from '$lib/components/PageHead.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { copyText } from '$lib/clipboard';
	import { formatAud, formatShortDate } from '$lib/formats';
	import type { DiscoveredPart } from '$lib/types';

	let { data, form } = $props();

	const RETAILER_LABEL: Record<string, string> = { pccg: 'PCCG', scorptec: 'Scorptec', umart: 'Umart' };
	const label = (r: string) => RETAILER_LABEL[r] ?? r;
	const day = formatShortDate;
	const money = (n: number | null) => (n == null ? '–' : formatAud(n));
	const isNew = (p: DiscoveredPart) => {
		const [y, m, d] = data.today.split('-').map(Number);
		const weekAgo = new Date(y, m - 1, d - 6);
		return new Date(`${p.firstSeen}T00:00:00`) >= weekAgo;
	};
	const ranAt = $derived(data.lastRun ? data.lastRun.finishedAt.slice(11, 16) : null);
	const summary = $derived(
		`${data.newThisWeek} new this week · ${data.untracked.length} untracked · ${data.conflicts.length} conflicts` +
			(data.lastRun ? ` · last checked ${day(data.lastRun.runDate)} ${ranAt}` : '')
	);
	let copied = $state<number | null>(null);
	let copyFailed = $state<number | null>(null);
	async function copy(p: DiscoveredPart) {
		const ok = await copyText(p.suggestedRow);
		copied = ok ? p.id : null;
		copyFailed = ok ? null : p.id;
	}
</script>

<PageHead title="Discover" description="Parts retailers sell that Trackaroo does not track yet." />

<div class="space-y-8">
	<div class="space-y-2">
		<PageHeader title="Discover" subtitle={summary} />
		{#if data.isStale}
			<p class="rounded-md bg-warning-soft px-3 py-2 text-sm text-text" role="status">
				{#if !data.lastRun}Discovery has not run yet.{:else if data.lastRun.runDate === data.today}No catalogues were saved today; showing the last results.{:else}Showing results from {day(data.lastRun.runDate)}: discovery has not run today yet.{/if}
			</p>
		{/if}
		{#if data.lastRun?.missing.length}
			<p class="text-xs text-text-muted">Missing today: {data.lastRun.missing.join(', ')}</p>
		{/if}
		{#if form?.error}<p class="text-sm text-danger" role="alert">{form.error}</p>{/if}
	</div>

	<section aria-labelledby="untracked-h">
		<h2 id="untracked-h" class="mb-2 text-sm font-semibold text-text">Untracked parts ({data.untracked.length})</h2>
		{#if data.untracked.length === 0}
			<p class="text-sm text-text-muted">Nothing untracked: every in-scope part on sale is tracked or ignored.</p>
		{:else}
			<ul data-testid="discover-untracked" class="divide-y divide-border rounded-md border border-border">
				{#each data.untracked as p (p.id)}
					<li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-3 {p.lastSeen < data.today ? 'opacity-60' : ''}">
						<details class="min-w-0 flex-1 basis-56">
							<summary class="cursor-pointer text-sm font-medium text-text">
								{p.displayName}
								{#if isNew(p)}<span class="ml-1 rounded bg-accent-soft px-1.5 py-0.5 text-xs font-semibold text-accent">NEW</span>{/if}
							</summary>
							<ul class="mt-1 list-disc pl-5 text-xs text-text-muted">
								{#each p.sampleTitles as t}<li>{t}</li>{/each}
							</ul>
						</details>
						<span class="text-xs text-text-muted">
							first seen {day(p.firstSeen)}{#if p.lastSeen < data.today} · last seen {day(p.lastSeen)}{/if}
						</span>
						<span class="text-xs text-text-muted">{p.listingCount} listings · {p.retailers.map(label).join(', ')}</span>
						<span class="tabular-nums text-sm text-text">
							from {#if p.minPriceUrl}<a href={p.minPriceUrl} target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-0.5">{money(p.minPrice)}<ArrowUpRight size={13} aria-hidden="true" /></a>{:else}{money(p.minPrice)}{/if}
						</span>
						<span class="flex gap-2">
							<form method="POST" action="?/track"><input type="hidden" name="id" value={p.id} /><button class="min-h-6 rounded-md border border-accent bg-accent-soft px-3 text-sm font-medium text-accent hover:bg-surface-hover">Track</button></form>
							<form method="POST" action="?/ignore"><input type="hidden" name="id" value={p.id} /><button class="min-h-6 rounded-md border border-border bg-surface px-3 text-sm text-text-muted hover:bg-surface-hover hover:text-text">Ignore</button></form>
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section aria-labelledby="requested-h">
		<h2 id="requested-h" class="mb-2 text-sm font-semibold text-text">Requested ({data.requested.length})</h2>
		<p class="mb-2 text-xs text-text-muted">
			These rows get added to <code>db/watchlist.csv</code> in a PR; the part is tracked after the next
			<code>deploy/redeploy.sh</code>. See README, "Discovering and adding new parts".
		</p>
		<ul data-testid="discover-requested" class="space-y-2">
			{#each data.requested as p (p.id)}
				<li class="rounded-md border border-border px-3 py-2">
					<div class="flex flex-wrap items-center justify-between gap-2">
						<span class="text-sm font-medium text-text">{p.displayName}</span>
						<span class="flex gap-2">
							<button type="button" class="min-h-6 rounded-md border border-border bg-surface px-3 text-sm text-text-muted hover:bg-surface-hover hover:text-text" onclick={() => copy(p)}>{copied === p.id ? 'Copied' : 'Copy row'}</button>
							<form method="POST" action="?/untrack"><input type="hidden" name="id" value={p.id} /><button class="min-h-6 rounded-md border border-border bg-surface px-3 text-sm text-text-muted hover:bg-surface-hover hover:text-text">Undo</button></form>
						</span>
					</div>
					<code class="mt-1 block overflow-x-auto whitespace-pre text-xs text-text-muted">{p.suggestedRow}</code>
				</li>
			{/each}
		</ul>
	</section>

	<section aria-labelledby="conflicts-h">
		<h2 id="conflicts-h" class="mb-2 text-sm font-semibold text-text">Conflicts ({data.conflicts.length})</h2>
		{#if data.conflicts.length === 0}
			<p class="text-sm text-text-muted">None: every listing matches its product.</p>
		{:else}
			<ul data-testid="discover-conflicts" class="divide-y divide-border rounded-md border border-border">
				{#each data.conflicts as c (c.listingId)}
					<li class="px-3 py-2 text-sm">
						<span class="text-text">{c.title}</span>
						<span class="block text-xs text-text-muted">
							{label(c.retailer)} · filed under <a href="/product/{c.filedProductId}" class="underline">{c.filedModel}</a> · {c.reason}
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<details>
		<summary class="cursor-pointer text-sm font-semibold text-text">Ignored ({data.ignored.length})</summary>
		<ul data-testid="discover-ignored" class="mt-2 divide-y divide-border rounded-md border border-border">
			{#each data.ignored as p (p.id)}
				<li class="flex items-center justify-between gap-2 px-3 py-2 text-sm">
					<span class="text-text">{p.displayName}</span>
					<form method="POST" action="?/unignore"><input type="hidden" name="id" value={p.id} /><button class="min-h-6 rounded-md border border-border bg-surface px-3 text-sm text-text-muted hover:bg-surface-hover hover:text-text">Un-ignore</button></form>
				</li>
			{/each}
		</ul>
	</details>

	{#if data.lastRun?.unrecognisedCount}
		<details>
			<summary class="cursor-pointer text-sm font-semibold text-text">Unrecognised titles ({data.lastRun.unrecognisedCount})</summary>
			<p class="mt-1 text-xs text-text-muted">Items in the CPU/GPU categories that name no known chip. Usually accessories; only a concern if a real CPU or GPU shows up here.</p>
			<ul class="mt-2 list-disc pl-5 text-xs text-text-muted">
				{#each data.lastRun.unrecognisedSamples as t}<li>{t}</li>{/each}
			</ul>
		</details>
	{/if}
</div>
