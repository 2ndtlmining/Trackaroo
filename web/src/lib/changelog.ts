// CHANGELOG.md -> the /changelog page. Only the subset the changelog uses is
// understood: "## X.Y.Z — YYYY-MM-DD" releases, a prose intro under a release,
// "### Section" headings, "- " bullets (wrapped or indented lines join the
// bullet above), and inline `code`, **bold**, [text](https://...) and #123
// issue references. "## Unreleased" is not shown: it is what the next release
// holds.

export interface ChangelogSection {
	title: string | null;
	items: string[];
}

export interface Release {
	version: string;
	date: string | null;
	intro: string[];
	sections: ChangelogSection[];
}

const ISSUES_URL = 'https://github.com/2ndtlmining/Trackaroo/issues/';
const RELEASE_RE = /^## (\d+\.\d+\.\d+)(?:\s+[—–-]\s+(\d{4}-\d{2}-\d{2}))?\s*$/;

export function parseChangelog(md: string): Release[] {
	const releases: Release[] = [];
	let current: Release | null = null;
	let section: ChangelogSection | null = null;
	let inItem = false;

	for (const raw of md.split(/\r?\n/)) {
		const line = raw.trimEnd();
		if (line.startsWith('## ')) {
			const m = RELEASE_RE.exec(line);
			current = m ? { version: m[1], date: m[2] ?? null, intro: [], sections: [] } : null;
			if (current) releases.push(current);
			section = null;
			inItem = false;
		} else if (!current) {
			continue;
		} else if (line === '') {
			inItem = false;
		} else if (line.startsWith('### ')) {
			section = { title: line.slice(4).trim(), items: [] };
			current.sections.push(section);
			inItem = false;
		} else if (/^[-*] /.test(line)) {
			if (!section) {
				section = { title: null, items: [] };
				current.sections.push(section);
			}
			section.items.push(line.slice(2).trim());
			inItem = true;
		} else if (inItem && section && /^\s/.test(raw)) {
			// A wrapped or indented line (including a sub-bullet) continues the item.
			const text = line.trim().replace(/^[-*] /, '');
			section.items[section.items.length - 1] += ` ${text}`;
		} else if (section === null) {
			current.intro.push(line.trim());
		} else {
			// Prose after a section started: keep it as its own item, never drop it.
			section.items.push(line.trim());
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

// One left-to-right pass over the raw text: each token (code span, link, bold,
// issue reference) is matched on the unescaped source and emitted with its
// parts escaped, so no rule can run inside another's output (no markup inside
// an href, no link inside a link).
const TOKEN_RE =
	/`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*|(^|(?<=[\s(]))#(\d+)\b/g;

export function renderInline(text: string): string {
	let out = '';
	let last = 0;
	for (const m of text.matchAll(TOKEN_RE)) {
		out += escapeHtml(text.slice(last, m.index));
		const [whole, code, linkText, href, bold, , issue] = m;
		if (code !== undefined) out += `<code>${escapeHtml(code)}</code>`;
		else if (href !== undefined) out += `<a href="${escapeHtml(href)}">${escapeHtml(linkText)}</a>`;
		else if (bold !== undefined) out += `<strong>${escapeHtml(bold)}</strong>`;
		else if (issue !== undefined) out += `<a href="${ISSUES_URL}${issue}">#${issue}</a>`;
		else out += escapeHtml(whole);
		last = m.index + whole.length;
	}
	return out + escapeHtml(text.slice(last));
}
