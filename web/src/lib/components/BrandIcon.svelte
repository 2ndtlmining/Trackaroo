<script lang="ts">
	import { siAmd, siIntel, siNvidia } from 'simple-icons';

	let { brand, size = 20 }: { brand: string; size?: number } = $props();

	const icons: Record<string, { path: string; hex: string; title: string }> = {
		AMD: { path: siAmd.path, hex: siAmd.hex, title: siAmd.title },
		NVIDIA: { path: siNvidia.path, hex: siNvidia.hex, title: siNvidia.title },
		Intel: { path: siIntel.path, hex: siIntel.hex, title: siIntel.title }
	};

	const icon = $derived(icons[brand]);
</script>

{#if icon}
	<svg
		viewBox="0 0 24 24"
		width={size}
		height={size}
		fill={`#${icon.hex}`}
		role="img"
		aria-label={icon.title}
		class="shrink-0"
	>
		<path d={icon.path} />
	</svg>
{/if}