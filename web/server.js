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

// Self-hosted fonts never change in place (a new font gets a new file name),
// so browsers may keep them for a year instead of revalidating on every page
// load (#63). sirv sets its own Cache-Control in writeHead's header object,
// so the override has to happen there, and only for successful responses.
const FONT_CACHE = 'public, max-age=31536000, immutable';

/**
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 */
function cacheFonts(req, res) {
	const path = (req.url ?? '').split('?')[0];
	if (!path.startsWith('/fonts/')) return;
	const writeHead = res.writeHead;
	/** @type {any} */ (res).writeHead = function (/** @type {number} */ code, /** @type {any[]} */ ...rest) {
		if ((code >= 200 && code < 300) || code === 304) {
			const headers = rest[rest.length - 1];
			if (headers && typeof headers === 'object' && !Array.isArray(headers)) {
				for (const key of Object.keys(headers)) {
					if (key.toLowerCase() === 'cache-control') delete headers[key];
				}
			}
			res.setHeader('Cache-Control', FONT_CACHE);
		}
		return writeHead.call(this, code, ...rest);
	};
}

// adapter-node checks every form POST's Origin against the origin it thinks it
// serves, and with no ORIGIN / PROTOCOL_HEADER it assumes https. This server is
// plain http on the LAN, so Track/Ignore, Retire/Keep and price alerts all
// failed with "Cross-site POST form submissions are forbidden". This wrapper is
// the one place that knows the real protocol (it never terminates TLS), so it
// stamps it on every request, overwriting anything a client sent.
export const PROTO_HEADER = 'x-trackaroo-proto';

/**
 * Tell adapter-node to read the protocol from PROTO_HEADER, unless the
 * deployment configured its own (ORIGIN or PROTOCOL_HEADER behind a proxy).
 * Must run before ./build/handler.js is imported: it reads env at load.
 *
 * @param {Record<string, string | undefined>} [env]
 */
export function configureOrigin(env = process.env) {
	if (env.ORIGIN || env.PROTOCOL_HEADER) return;
	env.PROTOCOL_HEADER = PROTO_HEADER;
}

/**
 * @param {(req: import('node:http').IncomingMessage, res: import('node:http').ServerResponse, next: () => void) => void} handler
 */
export function createServer(handler) {
	return http.createServer((req, res) => {
		req.headers[PROTO_HEADER] = 'http';
		cacheFonts(req, res);
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

/**
 * Mirrors adapter-node's own SIGTERM/SIGINT handling (see
 * `@sveltejs/adapter-node/files/index.js`'s `graceful_shutdown`): stop
 * accepting new connections, close idle ones immediately (a keep-alive
 * connection otherwise blocks `close()` until it times out on its own), let
 * in-flight requests drain, then exit. Forces the process closed after
 * `timeoutMs` if requests never drain.
 *
 * Exported rather than wired directly into `createServer()` so that function
 * stays free of process-level handlers for the compression-wrapper unit
 * tests, and so this can be exercised directly with an injected exit
 * function (never `process.exit`, which would kill the test runner) and a
 * fake signal source (never real `process`, so tests can't register
 * listeners for real OS signals).
 *
 * @param {import('node:http').Server} server
 * @param {{
 *   timeoutMs?: number,
 *   exit?: (code: number) => void,
 *   target?: import('node:events').EventEmitter,
 *   signals?: string[]
 * }} [options]
 * @returns {() => void} the shutdown handler, so tests can invoke it directly
 */
export function installShutdown(
	server,
	{ timeoutMs = 30_000, exit = process.exit, target = process, signals = ['SIGTERM', 'SIGINT'] } = {}
) {
	let shuttingDown = false;
	let exited = false;

	/**
	 * @param {number} code
	 * @param {NodeJS.Timeout} [forceTimer]
	 */
	function finish(code, forceTimer) {
		if (exited) return;
		exited = true;
		if (forceTimer) clearTimeout(forceTimer);
		exit(code);
	}

	function shutdown() {
		if (shuttingDown) return;
		shuttingDown = true;

		server.closeIdleConnections();

		const forceTimer = setTimeout(() => finish(1), timeoutMs);
		forceTimer.unref?.();

		server.close(() => finish(0, forceTimer));
	}

	for (const signal of signals) target.on(signal, shutdown);
	return shutdown;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
	// A non-literal specifier keeps TypeScript from statically resolving and
	// type-checking the generated ./build/handler.js bundle (svelte-check
	// otherwise pulls its whole dependency closure into the project).
	const handlerPath = './build/handler.js';
	configureOrigin();
	const { handler } = await import(handlerPath);
	const host = process.env.HOST ?? '0.0.0.0';
	const port = Number(process.env.PORT ?? 3000);
	const server = createServer(handler);
	installShutdown(server, { timeoutMs: Number(process.env.SHUTDOWN_TIMEOUT ?? 30) * 1000 });
	server.listen(port, host, () => {
		console.log(`Listening on http://${host}:${port}`);
	});
}
