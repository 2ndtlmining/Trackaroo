// Production entry: adapter-node's handler behind gzip compression.
//
// adapter-node compresses nothing it renders; only the /_app/immutable
// assets ship pre-compressed. Measured 28-Sep-2026 on prod: /movers was
// 1.52 MB of HTML on the wire, 64 KB gzipped (#28). There is no reverse
// proxy in front (owner decision), so compression lives here.
import http from 'node:http';
import { pathToFileURL } from 'node:url';
import compression from 'compression';

// `compression` skips responses that already carry Content-Encoding, so the
// pre-compressed immutable assets pass through untouched.
const compress = compression({ threshold: 1024 });

/**
 * @param {(req: import('node:http').IncomingMessage, res: import('node:http').ServerResponse, next: () => void) => void} handler
 */
export function createServer(handler) {
	return http.createServer((req, res) => {
		// `compression`'s types expect Express req/res; we run it directly
		// against the plain node:http objects adapter-node's handler also uses.
		compress(/** @type {any} */ (req), /** @type {any} */ (res), () => {
			handler(req, res, () => {
				res.statusCode = 404;
				res.end('Not found');
			});
		});
	});
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
	// A non-literal specifier keeps TypeScript from statically resolving and
	// type-checking the generated ./build/handler.js bundle (svelte-check
	// otherwise pulls its whole dependency closure into the project).
	const handlerPath = './build/handler.js';
	const { handler } = await import(handlerPath);
	const host = process.env.HOST ?? '0.0.0.0';
	const port = Number(process.env.PORT ?? 3000);
	createServer(handler).listen(port, host, () => {
		console.log(`Listening on http://${host}:${port}`);
	});
}
