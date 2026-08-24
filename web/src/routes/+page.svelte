<script lang="ts">
	import CategorySection from '$lib/components/CategorySection.svelte';
	import HealthStrip from '$lib/components/HealthStrip.svelte';

	let { data } = $props();
</script>

<svelte:head>
	<title>Trackaroo — Dashboard</title>
	<meta name="description" content="Latest tracked prices for AU CPUs and GPUs." />
</svelte:head>

<div>
	<h1 class="mb-4 text-xl font-semibold text-text">Dashboard</h1>

	<HealthStrip
		retailers={data.retailers}
		latestSnapshotDate={data.latestSnapshotDate}
		snapshotDays={data.snapshotDays}
		snapshotCount={data.snapshotCount}
	/>

	<div class="space-y-6">
		{#each data.sections as section (section.category)}
			<CategorySection
				title={section.title}
				href={section.href}
				trackedCount={section.trackedCount}
				cheapestPrice={section.cheapestPrice}
				deals={section.deals}
				drops={section.drops}
				rises={section.rises}
			/>
		{/each}
	</div>
</div>
