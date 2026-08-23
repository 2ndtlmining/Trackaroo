<script lang="ts">
	import { formatAud } from '$lib/formats';
	import type { AlertRow } from '$lib/server/repos';
	import type { AlertChannel } from '$lib/types';

	let {
		alerts,
		form = null
	}: {
		alerts: AlertRow[];
		/** fail() payload from the create action — re-renders the message inline. */
		form?: { error?: string; target_price?: string; channel?: AlertChannel } | null;
	} = $props();

	const CHANNELS: { value: AlertChannel; label: string }[] = [
		{ value: 'discord', label: 'Discord' },
		{ value: 'email', label: 'Email' },
		{ value: 'webhook', label: 'Webhook' }
	];
</script>

<section class="rounded-md border border-border bg-surface p-4">
	<h2 class="text-sm font-semibold text-text">Price alerts</h2>
	<p class="mt-1 text-xs text-text-muted">
		Get notified when this product's cheapest in-stock price drops to your target.
	</p>

	<form method="POST" action="?/create" class="mt-3 flex flex-wrap items-center gap-2">
		<label class="flex items-center gap-1.5 text-sm text-text">
			Alert me under <span class="text-text-muted">$</span>
			<input
				type="number"
				name="target_price"
				min="1"
				step="1"
				required
				aria-label="Target price in AUD"
				aria-invalid={form?.error ? 'true' : undefined}
				aria-describedby={form?.error ? 'alert-error' : undefined}
				value={form?.target_price ?? ''}
				placeholder="0"
				class="h-8 w-24 rounded-md border border-border bg-surface px-2 text-sm text-text placeholder:text-text-muted focus:border-accent focus:outline-none"
			/>
		</label>
		<select
			name="channel"
			aria-label="Notification channel"
			class="h-8 rounded-md border border-border bg-surface px-2 text-sm text-text focus:border-accent focus:outline-none"
		>
			{#each CHANNELS as opt}
				<option value={opt.value} selected={form?.channel === opt.value}>{opt.label}</option>
			{/each}
		</select>
		<label
			class="flex h-8 cursor-pointer select-none items-center gap-1.5 rounded-md border border-border bg-surface px-2 text-sm text-text"
		>
			<input
				type="checkbox"
				name="notify_on_restock"
				value="1"
				class="accent-accent"
				aria-label="Notify on restock"
			/>
			Notify on restock
		</label>
		<button
			type="submit"
			class="h-8 rounded-md border border-border bg-surface px-2.5 text-sm text-text-muted hover:bg-surface-hover hover:text-text"
		>
			Create alert
		</button>
	</form>

	{#if form?.error}
		<p id="alert-error" role="alert" class="mt-2 text-sm text-down">{form.error}</p>
	{/if}

	{#if alerts.length > 0}
		<div class="mt-4 border-t border-border pt-3">
			<h3 class="text-xs font-semibold uppercase tracking-wide text-text-muted">My alerts</h3>
			<ul class="mt-2 space-y-2">
				{#each alerts as alert (alert.id)}
					<li
						class="flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2"
					>
						<div class="flex flex-wrap items-center gap-2 text-sm">
							<span class="text-text">Under {formatAud(alert.target_price)}</span>
							<span class="text-text-muted">· {alert.channel}</span>
							{#if alert.notify_on_restock}
								<span class="text-text-muted">· restock</span>
							{/if}
							{#if alert.active === 0}
								<span class="text-text-muted">· paused</span>
							{/if}
						</div>
						<form method="POST" action="?/delete" class="shrink-0">
							<input type="hidden" name="alert_id" value={alert.id} />
							<button
								type="submit"
								class="text-xs text-text-muted hover:text-text"
								aria-label="Delete alert"
							>
								Delete
							</button>
						</form>
					</li>
				{/each}
			</ul>
		</div>
	{/if}
</section>
