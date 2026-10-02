// CHANGELOG.md -> the /changelog page. Only the subset the changelog uses is
// understood: "## X.Y.Z — YYYY-MM-DD" releases, "### Section" headings, "- "
// bullets, and inline `code`, **bold**, [text](https://...) and #123 issue
// references. "## Unreleased" is not shown: it is what the next release holds.

export interface ChangelogSection {
	title: string | null;
	items: string[];
}

export interface Release {
	version: string;
	date: string | null;
	sections: ChangelogSection[];
}

const ISSUES_URL = 'https://github.com/2ndtlmining/Trackaroo/issues/';
const RELEASE_RE = /^## (\d+\.\d+\.\d+)(?:\s+[—–-]\s+(\d{4}-\d{2}-\d{2}))?\s*$/;

export function parseChangelog(md: string): Release[] {
	const releases: Release[] = [];
	let current: Release | null = null;
	let section: ChangelogSection | null = null;

	for (const raw of md.split(/\r?\n/)) {
		const line = raw.trimEnd();
		if (line.startsWith('## ')) {
			const m = RELEASE_RE.exec(line);
			current = m ? { version: m[1], date: m[2] ?? null, sections: [] } : null;
			if (current) releases.push(current);
			section = null;
		} else if (!current) {
			continue;
		} else if (line.startsWith('### ')) {
			section = { title: line.slice(4).trim(), items: [] };
			current.sections.push(section);
		} else if (/^[-*] /.test(line)) {
			if (!section) {
				section = { title: null, items: [] };
				current.sections.push(section);
			}
			section.items.push(line.slice(2).trim());
		}
	}
	return releases;
}

function escapeHtml(s: string): string {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

// Escape first, then add the few tags we allow. Code spans are cut out before
// the other rules run so "#12" inside backticks is not turned into a link.
export function renderInline(text: string): string {
	return text
		.split(/(`[^`]+`)/)
		.map((part) => {
			if (/^`[^`]+`$/.test(part)) return `<code>${escapeHtml(part.slice(1, -1))}</code>`;
			return escapeHtml(part)
				.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
				.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>')
				.replace(/(^|[\s(])#(\d+)\b/g, `$1<a href="${ISSUES_URL}$2">#$2</a>`);
		})
		.join('');
}
