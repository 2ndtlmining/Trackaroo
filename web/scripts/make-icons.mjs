// Writes the PNG app icons from the same shape as static/favicon.svg (#25):
// a blue rounded square with a white rising price line. Zero dependencies --
// raw RGBA pixels, zlib and a CRC -- so no image toolchain enters the repo.
// Deterministic: re-running it rewrites byte-identical files.
//   node scripts/make-icons.mjs        (from web/)
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const BLUE = [0x25, 0x63, 0xeb, 255];
const WHITE = [255, 255, 255, 255];
const CLEAR = [0, 0, 0, 0];
// favicon.svg's polyline and end dot, on its 64-unit grid.
const LINE = [
	[10, 44],
	[24, 30],
	[34, 38],
	[54, 16]
];

function distToSegment(px, py, [ax, ay], [bx, by]) {
	const dx = bx - ax;
	const dy = by - ay;
	const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
	return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

// `fullBleed`: no transparent corners. A maskable icon gets its mask from the
// OS, and iOS paints transparent apple-touch corners black. The mark is
// scaled into the central 80% safe zone.
function pixel(x, y, size, fullBleed) {
	const u = ((x + 0.5) / size) * 64;
	const v = ((y + 0.5) / size) * 64;
	if (!fullBleed) {
		const r = 14; // favicon.svg rx
		const cx = Math.min(Math.max(u, r), 64 - r);
		const cy = Math.min(Math.max(v, r), 64 - r);
		if (Math.hypot(u - cx, v - cy) > r) return CLEAR;
	}
	const s = fullBleed ? 0.8 : 1;
	const gu = (u - 32) / s + 32;
	const gv = (v - 32) / s + 32;
	for (let i = 0; i < LINE.length - 1; i += 1) {
		if (distToSegment(gu, gv, LINE[i], LINE[i + 1]) <= 2.5) return WHITE;
	}
	if (Math.hypot(gu - 54, gv - 16) <= 4) return WHITE;
	return BLUE;
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
	let c = n;
	for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
	return c >>> 0;
});

function crc32(buf) {
	let c = 0xffffffff;
	for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
	return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
	const len = Buffer.alloc(4);
	len.writeUInt32BE(data.length);
	const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
	const crc = Buffer.alloc(4);
	crc.writeUInt32BE(crc32(body));
	return Buffer.concat([len, body, crc]);
}

export function png(size, fullBleed = false) {
	const ihdr = Buffer.alloc(13);
	ihdr.writeUInt32BE(size, 0);
	ihdr.writeUInt32BE(size, 4);
	ihdr[8] = 8; // bit depth
	ihdr[9] = 6; // RGBA
	const stride = size * 4 + 1;
	const raw = Buffer.alloc(size * stride);
	for (let y = 0; y < size; y += 1) {
		raw[y * stride] = 0; // filter: none
		for (let x = 0; x < size; x += 1) raw.set(pixel(x, y, size, fullBleed), y * stride + 1 + x * 4);
	}
	return Buffer.concat([
		Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
		chunk('IHDR', ihdr),
		chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
		chunk('IEND', Buffer.alloc(0))
	]);
}

const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'static');
const icons = [
	['icon-192.png', 192, false],
	['icon-512.png', 512, false],
	['icon-maskable-512.png', 512, true],
	['apple-touch-icon.png', 180, true]
];
for (const [name, size, fullBleed] of icons) {
	fs.writeFileSync(path.join(out, name), png(size, fullBleed));
	console.log(`[icons] wrote static/${name} (${size}px)`);
}
