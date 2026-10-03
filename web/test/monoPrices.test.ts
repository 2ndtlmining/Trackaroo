// #22 Task 5: every formatted AUD price in the markup is set in the mono,
// tabular face, so digits line up down a column and between rows. The scan
// reads each .svelte file's markup (script and style blocks stripped), finds
// every `{...}` text expression that calls formatAud(, formatSignedAud( or
// the discover page's money( wrapper, and requires `num` or `text-price` in
// the class of its element or that element's parent. Attribute values (aria-label, title) are not text and
// are skipped. Offenders are listed by file and expression.
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(__dirname, '..', 'src');
const PRICE_CALL = /\b(formatAud|formatSignedAud|money)\(/;
const MONO_CLASS = /(^|[\s'"{}?:])(num|text-price)(?=$|[\s'"{}?:])/;
const VOID = new Set(['br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'col', 'wbr', 'area', 'base']);

function walk(dir: string): string[] {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
		e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]
	);
}

// Read a `{...}` expression starting at text[i] === '{', honouring nested
// braces and string literals. Returns the index just past the closing brace.
function readBraces(text: string, i: number): number {
	let depth = 0;
	let quote: string | null = null;
	for (let j = i; j < text.length; j++) {
		const c = text[j];
		if (quote) {
			if (c === '\\') j++;
			else if (c === quote) quote = null;
			continue;
		}
		if (c === "'" || c === '"' || c === '`') quote = c;
		else if (c === '{') depth++;
		else if (c === '}' && --depth === 0) return j + 1;
	}
	return text.length;
}

// Read a tag `<...>`, skipping `>` inside braces and quoted attribute values.
function readTag(text: string, i: number): number {
	let quote: string | null = null;
	for (let j = i + 1; j < text.length; j++) {
		const c = text[j];
		if (quote) {
			if (c === quote) quote = null;
			else if (c === '{') j = readBraces(text, j) - 1;
			continue;
		}
		if (c === '"' || c === "'") quote = c;
		else if (c === '{') j = readBraces(text, j) - 1;
		else if (c === '>') return j + 1;
	}
	return text.length;
}

function classOf(tag: string): string {
	const m = tag.match(/\sclass=("([^"]*)"|'([^']*)'|\{[^}]*\})/);
	return m ? (m[2] ?? m[3] ?? m[1]) : '';
}

export function priceOffenders(source: string): string[] {
	const markup = source
		.replace(/<script[\s\S]*?<\/script>/g, '')
		.replace(/<style[\s\S]*?<\/style>/g, '')
		.replace(/<!--[\s\S]*?-->/g, '');
	const stack: string[] = [];
	const out: string[] = [];
	let i = 0;
	while (i < markup.length) {
		const c = markup[i];
		if (c === '<' && /[A-Za-z/]/.test(markup[i + 1] ?? '')) {
			const end = readTag(markup, i);
			const tag = markup.slice(i, end);
			const name = tag.match(/^<\/?([A-Za-z][\w.:-]*)/)?.[1] ?? '';
			if (tag.startsWith('</')) stack.pop();
			else if (!tag.endsWith('/>') && !VOID.has(name.toLowerCase())) stack.push(classOf(tag));
			i = end;
		} else if (c === '{') {
			const end = readBraces(markup, i);
			const expr = markup.slice(i, end);
			if (PRICE_CALL.test(expr) && !/^\{[#:/@]/.test(expr)) {
				const own = stack[stack.length - 1] ?? '';
				const parent = stack[stack.length - 2] ?? '';
				if (!MONO_CLASS.test(` ${own} `) && !MONO_CLASS.test(` ${parent} `)) out.push(expr);
			}
			i = end;
		} else i++;
	}
	return out;
}

describe('mono prices (#22 Task 5)', () => {
	it('the scanner flags a bare price and accepts .num on the element or its parent', () => {
		expect(priceOffenders('<p>Under {formatAud(5)}</p>')).toEqual(['{formatAud(5)}']);
		expect(priceOffenders('<p class="num">{formatAud(5)}</p>')).toEqual([]);
		expect(priceOffenders('<td class="text-price x">{formatAud(5)}</td>')).toEqual([]);
		expect(priceOffenders('<p class="x num"><b>{formatAud(5)}</b></p>')).toEqual([]);
		expect(priceOffenders('<a aria-label="Buy {formatAud(5)}">Buy</a>')).toEqual([]);
		expect(priceOffenders('<p class="numeric">{formatAud(5)}</p>')).toHaveLength(1);
	});

	it('every formatted AUD price in web/src markup is mono', () => {
		const offenders = walk(SRC)
			.filter((f) => f.endsWith('.svelte'))
			.flatMap((f) =>
				priceOffenders(fs.readFileSync(f, 'utf-8')).map((e) => `${path.relative(SRC, f)}: ${e}`)
			);
		expect(offenders).toEqual([]);
	});
});
