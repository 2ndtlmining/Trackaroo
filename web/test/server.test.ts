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
