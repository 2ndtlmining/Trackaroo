<script lang="ts">
	import CategorySection from '$lib/components/CategorySection.svelte';
	import HealthStrip from '$lib/components/HealthStrip.svelte';
	import PageHead from '$lib/components/PageHead.svelte';

	let { data } = $props();
</script>

<PageHead
	description="Today's cheapest AU prices, deals and biggest price moves for tracked CPUs and GPUs."
/>

<div>
	<h1 class="mb-4 text-xl font-semibold text-text">Dashboard</h1>

	<HealthStrip
		retailers={data.retailers}
		latestSnapshotDate={data.latestSnapshotDate}
		snapshotDays={data.snapshotDays}
		snapshotCount={data.snapshotCount}
		dbSizeBytes={data.dbSizeBytes}
	/>

	<div class="space-y-6">
		{#each data.sections as section (section.category)}
			<CategorySection
				title={section.title}
				href={section.href}
				trackedCount={section.trackedCount}
				availableCount={section.availableCount}
				cheapestPrice={section.cheapestPrice}
				deals={section.deals}
				drops={section.drops}
				rises={section.rises}
			/>
		{/each}
	</div>
</div>
