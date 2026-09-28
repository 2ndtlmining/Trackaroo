import { afterEach, describe, expect, it } from 'vitest';
import type { Server } from 'node:http';
import { gunzipSync } from 'node:zlib';
import { createServer } from '../server.js';

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
