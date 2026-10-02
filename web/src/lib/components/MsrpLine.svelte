<script lang="ts">
	import BadgeDollarSign from '@lucide/svelte/icons/badge-dollar-sign';
	import Info from '@lucide/svelte/icons/info';
	import { formatAud } from '$lib/formats';
	import type { FxRate } from '$lib/models';
	import {
		MSRP_TONE_CLASS,
		msrpAud,
		msrpDelta,
		msrpExplanation,
		msrpPhrase,
		msrpTone
	} from '$lib/msrp';

	// The headline price against the US launch MSRP in today's AUD (Task 3,
	// #32). Renders nothing unless the price, the MSRP and a rate are all known.
	let {
		price,
		msrpUsd,
		fx
	}: {
		price: number | null;
		msrpUsd: number | null;
		fx: FxRate | null;
	} = $props();

	const id = $props.id();
	const aud = $derived(msrpAud(msrpUsd, fx));
	const delta = $derived(msrpDelta(price, aud));
	let open = $state(false);

	function onKey(event: KeyboardEvent) {
		if (open && event.key === 'Escape') open = false;
	}
</script>

<svelte:window onkeydown={onKey} />

{#if delta !== null && aud !== null && msrpUsd !== null && fx !== null}
	<div class="text-sm" data-testid="msrp-line">
		<p class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
			<span class="inline-flex items-center gap-1.5 font-medium {MSRP_TONE_CLASS[msrpTone(delta)]}">
				<BadgeDollarSign size={16} aria-hidden="true" class="shrink-0" />
				{msrpPhrase(delta)}
			</span>
			<span class="text-text-muted">≈<span class="num">A{formatAud(Math.round(aud))}</span> inc. GST</span>
			<button
				type="button"
				class="-m-1 inline-flex size-6 items-center justify-center rounded-md text-text-muted hover:bg-surface-hover hover:text-text"
				aria-label="How the MSRP is converted"
				aria-expanded={open}
				aria-controls={`${id}-msrp`}
				onclick={() => (open = !open)}
			>
				<Info size={14} aria-hidden="true" />
			</button>
		</p>
		<p
			id={`${id}-msrp`}
			class="mt-1.5 max-w-prose rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text-muted"
			hidden={!open}
		>
			<span class="text-text">{msrpExplanation(msrpUsd, fx)}</span>
			<span class="block">US prices exclude sales tax, so GST is added to compare like with like.</span>
		</p>
	</div>
{/if}
