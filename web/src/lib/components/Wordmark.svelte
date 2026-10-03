<script lang="ts">
	let { size = 'header' }: { size?: 'header' | 'large' } = $props();
</script>

<a
	href="/"
	aria-label="Trackaroo home"
	class="font-mono font-semibold tracking-tight text-text no-underline hover:no-underline {size ===
	'large'
		? 'text-[28px] leading-9'
		: 'text-[18px] leading-6'}">trackaroo<span class="text-accent" aria-hidden="true">_</span></a
>
