// Copy text to the clipboard. Prod is served over plain http, where
// navigator.clipboard is undefined, so fall back to a temporary <textarea> and
// document.execCommand('copy'). Resolves false when neither works.
export async function copyText(text: string): Promise<boolean> {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {
		// fall through to the textarea fallback
	}
	let area: HTMLTextAreaElement | null = null;
	try {
		area = document.createElement('textarea');
		area.value = text;
		area.setAttribute('readonly', '');
		area.style.position = 'fixed';
		area.style.opacity = '0';
		document.body.appendChild(area);
		area.select();
		return document.execCommand('copy');
	} catch {
		return false;
	} finally {
		area?.remove();
	}
}
