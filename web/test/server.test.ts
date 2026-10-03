import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Server } from 'node:http';
import { EventEmitter } from 'node:events';
import net from 'node:net';
import { gunzipSync } from 'node:zlib';
import { createServer, installShutdown } from '../server.js';

const BODY = '<html>' + 'x'.repeat(20_000) + '</html>';
let server: Server;

function start(handler: (req: any, res: any) => void): Promise<string> {
	server = createServer(handler);
	return new Promise((resolve) =>
		server.listen(0, () => resolve(`http://127.0.0.1:${(server.address() as any).port}`))
	);
}
afterEach(() => server?.close());

describe('compression wrapper (#28)', () => {
	it('gzips HTML when the client accepts it', async () => {
		const base = await start((_req, res) => {
			res.setHeader('content-type', 'text/html');
			res.end(BODY);
		});
		const res = await fetch(base, { headers: { 'accept-encoding': 'gzip' } });
		expect(res.headers.get('content-encoding')).toBe('gzip');
		expect(Number(res.headers.get('content-length') ?? 0)).toBeLessThan(BODY.length);
	});

	it('sends plain bodies to clients that do not accept gzip', async () => {
		const base = await start((_req, res) => {
			res.setHeader('content-type', 'text/html');
			res.end(BODY);
		});
		const raw = await new Promise<string>((resolve) => {
			import('node:http').then(({ get }) =>
				get(base, { headers: { 'accept-encoding': 'identity' } }, (r) => {
					let s = '';
					r.on('data', (c) => (s += c));
					r.on('end', () => resolve(`${r.headers['content-encoding'] ?? 'none'}|${s.length}`));
				})
			);
		});
		expect(raw).toBe(`none|${BODY.length}`);
	});

	it('leaves already-encoded (pre-compressed asset) responses alone', async () => {
		const pre = gunzipSync; // silence unused import in some TS configs
		void pre;
		const base = await start((_req, res) => {
			res.setHeader('content-type', 'application/javascript');
			res.setHeader('content-encoding', 'br');
			res.end('already-br-bytes');
		});
		const res = await fetch(base, { headers: { 'accept-encoding': 'gzip, br' } });
		expect(res.headers.get('content-encoding')).toBe('br');
	});
});

describe('font caching (#63)', () => {
	const IMMUTABLE = 'public, max-age=31536000, immutable';

	it('marks /fonts/ responses immutable even when the static handler sets its own header', async () => {
		// sirv passes Cache-Control in writeHead's header object.
		const base = await start((_req, res) => {
			res.writeHead(200, { 'Cache-Control': 'no-cache', 'Content-Type': 'font/woff2' });
			res.end('wOF2');
		});
		const res = await fetch(`${base}/fonts/ibm-plex-sans-latin-400-normal.woff2`);
		expect(res.headers.get('cache-control')).toBe(IMMUTABLE);
	});

	it('also wins over a header set with setHeader', async () => {
		const base = await start((_req, res) => {
			res.setHeader('Cache-Control', 'no-cache');
			res.end('wOF2');
		});
		const res = await fetch(`${base}/fonts/x.woff2`);
		expect(res.headers.get('cache-control')).toBe(IMMUTABLE);
	});

	it('leaves every other path alone', async () => {
		const base = await start((_req, res) => {
			res.writeHead(200, { 'Cache-Control': 'no-cache', 'Content-Type': 'text/html' });
			res.end('ok');
		});
		for (const path of ['/', '/products', '/fontsx/a.woff2', '/favicon.svg']) {
			const res = await fetch(`${base}${path}`);
			expect(res.headers.get('cache-control')).toBe('no-cache');
		}
	});

	it('also marks a 304 revalidation and a HEAD request', async () => {
		const notModified = await start((_req, res) => {
			res.writeHead(304);
			res.end();
		});
		const r304 = await fetch(`${notModified}/fonts/x.woff2`);
		expect(r304.status).toBe(304);
		expect(r304.headers.get('cache-control')).toBe(IMMUTABLE);
		server.close();
		const head = await start((_req, res) => {
			res.writeHead(200, { 'Cache-Control': 'no-cache', 'Content-Type': 'font/woff2' });
			res.end();
		});
		const rHead = await fetch(`${head}/fonts/x.woff2?v=1`, { method: 'HEAD' });
		expect(rHead.headers.get('cache-control')).toBe(IMMUTABLE);
	});

	it('does not cache error responses', async () => {
		const base = await start((_req, res) => {
			res.writeHead(404, { 'Content-Type': 'text/plain' });
			res.end('Not found');
		});
		const res = await fetch(`${base}/fonts/missing.woff2`);
		expect(res.status).toBe(404);
		expect(res.headers.get('cache-control')).toBeNull();
	});
});

describe('graceful shutdown (#28 follow-up)', () => {
	// A fake signal source, never the real `process` -- so this never
	// registers a listener for a real OS signal on the test runner's process.
	for (const signal of ['SIGTERM', 'SIGINT']) {
		it(`closes the server and exits(0) on ${signal}`, async () => {
			const base = await start((_req, res) => res.end('ok'));
			const target = new EventEmitter();
			const exit = vi.fn();

			installShutdown(server, { exit, target, timeoutMs: 5000 });
			target.emit(signal);

			await new Promise<void>((resolve) => server.once('close', () => resolve()));
			expect(exit).toHaveBeenCalledExactlyOnceWith(0);

			// fetch after close() should fail to connect.
			await expect(fetch(base)).rejects.toBeTruthy();
		});
	}

	it('force-exits after the timeout when a connection never drains', async () => {
		server = createServer((_req, res) => res.end('ok'));
		const port: number = await new Promise((resolve) =>
			server.listen(0, () => resolve((server.address() as any).port))
		);
		// An open keep-alive-style socket that is never ended holds close()
		// open forever on its own, forcing the timeout path.
		const socket = net.connect(port, '127.0.0.1');
		await new Promise((resolve) => socket.on('connect', resolve));

		const target = new EventEmitter();
		const exit = vi.fn();
		installShutdown(server, { exit, target, timeoutMs: 30 });
		target.emit('SIGTERM');

		await new Promise((resolve) => setTimeout(resolve, 150));
		expect(exit).toHaveBeenCalledExactlyOnceWith(1);

		socket.destroy();
	});

	it('ignores a second signal once shutdown has started', async () => {
		const base = await start((_req, res) => res.end('ok'));
		void base;
		const target = new EventEmitter();
		const exit = vi.fn();

		installShutdown(server, { exit, target, timeoutMs: 5000 });
		target.emit('SIGTERM');
		target.emit('SIGINT');

		await new Promise<void>((resolve) => server.once('close', () => resolve()));
		expect(exit).toHaveBeenCalledExactlyOnceWith(0);
	});
});
