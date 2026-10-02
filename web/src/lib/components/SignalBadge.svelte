<script lang="ts">
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import Minus from '@lucide/svelte/icons/minus';
	import TrendingDown from '@lucide/svelte/icons/trending-down';
	import TrendingUp from '@lucide/svelte/icons/trending-up';
	import CalendarClock from '@lucide/svelte/icons/calendar-clock';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import type { Signal, SignalIcon, SignalTone } from '$lib/buySignals';

	// One buying signal (#31): a tinted icon disc, the short claim, then the
	// evidence behind it. The icon is decorative; the words carry the meaning,
	// so the badge never relies on colour or the icon alone.
	let { signal }: { signal: Signal } = $props();

	const ICONS: Record<SignalIcon, typeof CircleCheck> = {
		check: CircleCheck,
		dash: Minus,
		down: TrendingDown,
		up: TrendingUp,
		calendar: CalendarClock,
		alert: TriangleAlert
	};

	// Existing semantic tokens only (contrast.test.ts covers each pair).
	const DISC: Record<SignalTone, string> = {
		good: 'bg-success-soft text-success',
		warn: 'bg-warning-soft text-warning',
		bad: 'bg-danger-soft text-danger',
		neutral: 'bg-surface-hover text-text-muted'
	};

	const Icon = $derived(ICONS[signal.icon]);
</script>

<li
	class="flex items-start gap-3 rounded-2xl border border-border bg-surface py-2.5 pr-3.5 pl-2.5"
	data-testid="signal"
	data-tone={signal.tone}
>
	<span class="mt-px inline-flex size-6 shrink-0 items-center justify-center rounded-full {DISC[signal.tone]}">
		<Icon size={14} strokeWidth={2.25} aria-hidden="true" />
	</span>
	<span class="min-w-0">
		<span class="block text-sm tabular-nums leading-snug font-semibold text-text" data-testid="signal-claim">
			{signal.claim}
		</span>
		<span class="mt-0.5 block tabular-nums text-xs leading-snug text-text-muted" data-testid="signal-evidence">
			{signal.evidence}
		</span>
	</span>
</li>
