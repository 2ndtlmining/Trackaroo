<script lang="ts">
	import Archive from '@lucide/svelte/icons/archive';
	import Clock from '@lucide/svelte/icons/clock';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import { formatShortDate } from '$lib/formats';
	import { retailerLabel } from '$lib/filters';
	import type { RetireSuggestion } from '$lib/types';

	let { suggestions }: { suggestions: RetireSuggestion[] } = $props();

	const lastSeen = (s: RetireSuggestion) =>
		s.lastSeen
			? `last seen ${formatShortDate(s.lastSeen)}${s.lastSeenRetailer ? ` at ${retailerLabel(s.lastSeenRetailer)}` : ''}`
			: 'never listed';
	const btn =
		'inline-flex min-h-7 items-center gap-1.5 rounded-md border px-3 text-sm hover:bg-surface-hover';
	const quiet = `${btn} border-border bg-surface text-text-muted hover:text-text`;
</script>

{#if suggestions.length > 0}
	<section aria-labelledby="retire-h">
		<h2 id="retire-h" class="mb-2 flex items-center gap-1.5 text-sm font-semibold text-text">
			<Archive size={15} aria-hidden="true" />Ready to retire ({suggestions.length})
		</h2>
		<p class="mb-2 text-xs text-text-muted">
			Tracked parts no retailer has listed for 30 days. Retire asks for the watchlist change; Keep hides one for 90 days.
		</p>
		<ul data-testid="discover-retire" class="divide-y divide-border rounded-xl border border-border-card bg-surface shadow-card">
			{#each suggestions as s (s.productId)}
				<li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-3">
					<span class="min-w-0 flex-1 basis-48 text-sm font-medium text-text">{s.model}</span>
					<span class="text-xs text-text-muted">{lastSeen(s)}</span>
					{#if s.decision === 'requested'}
						<span class="flex items-center gap-2">
							<span class="rounded bg-accent-soft px-1.5 py-0.5 text-xs font-semibold text-accent">Requested</span>
							<form method="POST" action="?/undoRetire">
								<input type="hidden" name="productId" value={s.productId} />
								<button class={quiet}><Undo2 size={14} aria-hidden="true" />Undo</button>
							</form>
						</span>
					{:else}
						<span class="flex gap-2">
							<form method="POST" action="?/retire">
								<input type="hidden" name="productId" value={s.productId} />
								<button class="{btn} border-accent bg-accent-soft font-medium text-accent"><Archive size={14} aria-hidden="true" />Retire</button>
							</form>
							<form method="POST" action="?/keep">
								<input type="hidden" name="productId" value={s.productId} />
								<button class={quiet}><Clock size={14} aria-hidden="true" />Keep</button>
							</form>
						</span>
					{/if}
				</li>
			{/each}
		</ul>
	</section>
{/if}
