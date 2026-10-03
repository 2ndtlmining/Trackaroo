<script lang="ts" generics="T extends string">
	// One catalogue filter fieldset of checkboxes (Brand, Generation), shared by
	// CatalogFilters' inline form and its phone dialog (#61).
	let {
		legend,
		legendClass,
		name,
		options,
		selected,
		onChange
	}: {
		legend: string;
		legendClass: string;
		// The GET parameter each checkbox submits under.
		name: string;
		options: { value: T; label: string }[];
		selected: T[];
		onChange: (next: T[]) => void;
	} = $props();

	function toggle(value: T, on: boolean): T[] {
		return on ? [...selected.filter((v) => v !== value), value] : selected.filter((v) => v !== value);
	}
</script>

<fieldset>
	<legend class={legendClass}>{legend}</legend>
	<div class="flex flex-wrap items-center gap-3">
		{#each options as o (o.value)}
			<label class="flex h-9 cursor-pointer select-none items-center gap-1.5 text-sm text-text">
				<input
					type="checkbox"
					{name}
					value={o.value}
					class="size-4 accent-accent"
					checked={selected.includes(o.value)}
					onchange={(e) => onChange(toggle(o.value, (e.target as HTMLInputElement).checked))}
				/>
				{o.label}
			</label>
		{/each}
	</div>
</fieldset>
