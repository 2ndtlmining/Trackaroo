<script lang="ts">
	import { SITE_DESCRIPTION, SITE_NAME, pageTitle } from '$lib/head';

	// The only component that writes <title> and the description. Text-only
	// OG/Twitter tags: the app is LAN-only, so an og:image or og:url would
	// point at a host nobody else can reach (#25, design U-D2).
	// `titleOverride` is for a caller that already built a full title with
	// productPageTitle(); passing that as `title` would double the suffix.
	let {
		title = null,
		titleOverride = null,
		description = SITE_DESCRIPTION
	}: { title?: string | null; titleOverride?: string | null; description?: string } = $props();

	const fullTitle = $derived(titleOverride ?? pageTitle(title));
</script>

<svelte:head>
	<title>{fullTitle}</title>
	<meta name="description" content={description} />
	<meta property="og:site_name" content={SITE_NAME} />
	<meta property="og:type" content="website" />
	<meta property="og:title" content={fullTitle} />
	<meta property="og:description" content={description} />
	<meta name="twitter:card" content="summary" />
</svelte:head>
