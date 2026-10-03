// Renders the PNG app icons from static/favicon.svg with Playwright's chromium
// (already a devDependency), so the PNGs always match the favicon (#22).
//   node scripts/render-icons.mjs        (from web/)
// Writes icon-192, icon-512, apple-touch-icon (180, full-bleed: iOS paints
// transparent corners black) and icon-maskable-512 (full-bleed, mark scaled
// to 80% so it stays inside the maskable safe zone).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const STATIC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'static');
const svg = fs.readFileSync(path.join(STATIC, 'favicon.svg'), 'utf-8');
const BLUE = '#2563eb';

// The favicon's mark: everything after the background rect.
const mark = svg.replace(/^[\s\S]*?<rect[^>]*rx="14"[^>]*\/>/, '').replace('</svg>', '');

function variantSvg(variant) {
	if (variant === 'rounded') return svg;
	const scale = variant === 'maskable' ? 0.8 : 1;
	const t = (32 * (1 - scale)).toFixed(2);
	return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" fill="${BLUE}"/>
<g transform="translate(${t} ${t}) scale(${scale})">${mark}</g></svg>`;
}

const JOBS = [
	['icon-192.png', 192, 'rounded'],
	['icon-512.png', 512, 'rounded'],
	['apple-touch-icon.png', 180, 'full'],
	['icon-maskable-512.png', 512, 'maskable']
];

const browser = await chromium.launch();
try {
	for (const [file, size, variant] of JOBS) {
		const page = await browser.newPage({ viewport: { width: size, height: size } });
		await page.setContent(
			`<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${variantSvg(variant)}`
		);
		await page.screenshot({ path: path.join(STATIC, file), omitBackground: true });
		await page.close();
		console.log('wrote', file);
	}
} finally {
	await browser.close();
}
