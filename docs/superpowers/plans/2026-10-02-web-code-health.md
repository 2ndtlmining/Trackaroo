# Web Code Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 1,416-line `web/src/lib/server/repos.ts` into focused query modules, remove dead code, de-duplicate the "daily cheapest in stock" SQL, move DTO types out of `$lib/server`, and use one rule for "how old" — with **no change to what any page shows** except the intended "Updated …" wording.

**Architecture:** A frozen copy of today's `repos.ts` (`web/test/legacy/repos.legacy.ts`) is the oracle: an equivalence suite calls every legacy query and its new counterpart on the same DB and deep-compares the results, on the seeded test DB in CI and on a read-only temp copy of the real local DB on demand. Refactors happen behind that net. `repos.ts` ends as a barrel re-exporting `src/lib/server/queries/*`, so no route import changes.

**Tech Stack:** SvelteKit 2 / Svelte 5, TypeScript, better-sqlite3, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-02-web-code-health-design.md`

## Global Constraints

- **Data safety (owner requirement):** no changes to `db/schema.sql`, `migrate.py`, any Python, `data/`, backups, `Dockerfile`, `docker-compose.yml`, `deploy/`. No new writes. `upsertAlert`, `deleteAlert` and the `/discover` actions keep their SQL unchanged (they may move file).
- **Never open `db/trackaroo.db` directly in tests.** The real-DB equivalence run uses a temp **copy**, opened read-only.
- Every query whose SQL changes must pass the equivalence suite (Task 1) on the seeded DB and on the real-DB copy before its task completes.
- After every task: `npm run check` 0 errors 0 warnings, `npm test`, `npm run test:e2e` green; backend `python -m pytest -q` green (should be untouched).
- No file under `web/src/lib/server/` over 350 lines at the end; no client file (`*.svelte`, or `web/src/lib/**` outside `server/`) imports `$lib/server`.
- Only intended visible change: the product page "Updated …" stamp (Task 6).
- Code style: tabs, single quotes, existing comment density.

## Review Focus

1. **A query refactor that changes results only on real data** (rare listings, NULL prices, bundle titles, sold-out days): the synthetic seeded DB can miss it. Task 1 adds the real-DB-copy run and Tasks 4/5/7 require it.
2. **Row ordering differences** (SQL without a total ORDER BY can return ties in a different order after a rewrite): the equivalence suite compares exact arrays, so a tie-order change fails loudly; fix by preserving the original ORDER BY, never by sorting in the test. Task 1 states this.
3. **`Map` return types** (`getLaunchDates`, `getCategoryCounts`, `getAvailableCounts`): deep-equality must compare Map entries — Task 1's `normalise` converts Maps to sorted entry arrays.
4. **Time-dependent output** (anything using `new Date()`): legacy and new are called back-to-back in the same test, but a call straddling midnight could differ — Task 1 calls both with the same pinned arguments and the suite is fast; a flake there is a bug to report, not to retry.
5. **The write paths** (`upsertAlert`, `deleteAlert`): not covered by read equivalence — Task 1 adds an equivalence test that runs each on two fresh copies of the seeded DB and compares the resulting `price_alerts` rows.

## File Structure

| File | Responsibility |
|---|---|
| `web/test/legacy/repos.legacy.ts` (new, deleted in Task 7) | Frozen copy of today's `repos.ts`, the oracle |
| `web/test/equivalence.test.ts` (new, deleted in Task 7) | Legacy vs new, every exported query |
| `web/scripts/equivalence-real-db.mjs` (new) | Copies `db/trackaroo.db` to a temp file and runs the equivalence suite against it |
| `web/src/lib/models.ts` (new) | DTO types used by client code |
| `web/src/lib/server/queries/*.ts` (new) | catalog, history, stats, deals, movers, compare, alerts, health, sql (fragments) |
| `web/src/lib/server/repos.ts` (rewritten) | Barrel: `export *` from queries + types |
| `web/test/boundaries.test.ts` (new) | Client-import guard + 350-line guard |
| `web/src/lib/formats.ts` (modify) | `updatedLabel`; remove `freshnessLabel` |

---

### Task 1: Equivalence oracle and baseline

**Files:**
- Create: `web/test/legacy/repos.legacy.ts`, `web/test/equivalence.test.ts`, `web/scripts/equivalence-real-db.mjs`
- Modify: `web/package.json` (script `test:equiv-real`)

**Interfaces:**
- Produces: `npm run test:equiv-real` (runs the equivalence suite against a temp copy of `../db/trackaroo.db`); env `TRACKAROO_EQUIV_DB` read by the suite (a path; when unset the suite uses the seeded DB only).

- [ ] **Step 1: Freeze the oracle**

```bash
mkdir -p web/test/legacy
cp web/src/lib/server/repos.ts web/test/legacy/repos.legacy.ts
```

At the top of the copy add:

```ts
// FROZEN copy of src/lib/server/repos.ts at the start of the #30 refactor.
// The oracle for test/equivalence.test.ts. Never edit; deleted in Task 7.
```

Fix only its relative imports so it compiles from `web/test/legacy/` (e.g. `'./db'` -> `'../../src/lib/server/db'`, `'$lib/...'` imports stay — vitest resolves `$lib`). No other edit.

- [ ] **Step 2: Write the equivalence suite**

```ts
// web/test/equivalence.test.ts
// #30 safety net: every exported query in src/lib/server/repos.ts must return
// exactly what the frozen legacy copy returns, on the same DB. Runs on the
// seeded test DB always, and on a read-only copy of the real DB when
// TRACKAROO_EQUIV_DB is set (npm run test:equiv-real). Exact arrays are
// compared: if a rewrite changes tie order, restore the original ORDER BY --
// never sort inside this test.
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createSeededDb, type SeededDb } from './helpers/seed';
import * as legacy from './legacy/repos.legacy';
import * as current from '../src/lib/server/repos';

function normalise(v: unknown): unknown {
	if (v instanceof Map) return [...v.entries()].map(([k, x]) => [k, normalise(x)]).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
	if (Array.isArray(v)) return v.map(normalise);
	if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, normalise(x)]));
	return v;
}

type AnyDb = any;
interface Target { name: string; db: AnyDb; close: () => void }
const targets: Target[] = [];
let seeded: SeededDb;

beforeAll(() => {
	seeded = createSeededDb();
	targets.push({ name: 'seeded', db: seeded.db, close: () => seeded.close() });
	const real = process.env.TRACKAROO_EQUIV_DB;
	if (real) {
		const db = new Database(real, { readonly: true, fileMustExist: true });
		targets.push({ name: 'real-copy', db, close: () => db.close() });
	}
});
afterAll(() => targets.forEach((t) => t.close()));

function sampleIds(db: AnyDb) {
	const products = db.prepare('SELECT id FROM products WHERE tracked = 1 ORDER BY id').all().map((r: any) => r.id);
	return { first: products[0], some: products.slice(0, 3), all: products };
}

// [name, (repo, db, ids) => result]. One entry per exported query and per
// meaningful argument shape. Add an entry whenever a function or parameter is
// added; remove one only when the function is deliberately deleted (Task 2).
const CASES: Array<[string, (r: any, db: AnyDb, ids: ReturnType<typeof sampleIds>) => unknown]> = [
	['getTrackedProducts gpu', (r, db) => r.getTrackedProducts(db, 'gpu')],
	['getTrackedProducts cpu', (r, db) => r.getTrackedProducts(db, 'cpu')],
	['getLaunchDates gpu', (r, db) => r.getLaunchDates(db, 'gpu')],
	['getProductIndex', (r, db) => r.getProductIndex(db)],
	['getHeaderStats', (r, db) => r.getHeaderStats(db)],
	['getRetailerFreshness', (r, db) => r.getRetailerFreshness(db)],
	['getCategoryCounts', (r, db) => r.getCategoryCounts(db)],
	['getAvailableCounts', (r, db) => r.getAvailableCounts(db)],
	['getLatestListings gpu', (r, db) => r.getLatestListings(db, { category: 'gpu' })],
	['getLatestListings cpu', (r, db) => r.getLatestListings(db, { category: 'cpu' })],
	['getSparklines', (r, db, ids) => r.getSparklines(db, ids.all)],
	['getProductStats 30', (r, db, ids) => ids.some.map((id: number) => r.getProductStats(db, id))],
	['getProductStats 90', (r, db, ids) => ids.some.map((id: number) => r.getProductStats(db, id, 90))],
	['getProductDealStats', (r, db, ids) => r.getProductDealStats(db, ids.all)],
	['getPriceBand', (r, db, ids) => ids.some.map((id: number) => r.getPriceBand(db, id))],
	['getRetailerLatest', (r, db) => r.getRetailerLatest(db)],
	['getProductHistory', (r, db, ids) => ids.some.map((id: number) => r.getProductHistory(db, id, r.getRetailerLatest(db)))],
	['getProductHistory missing', (r, db) => r.getProductHistory(db, 999999, r.getRetailerLatest(db))],
	['getCheapestPerModel gpu', (r, db) => r.getCheapestPerModel(db, 'gpu')],
	['getCheapestPerModel cpu', (r, db) => r.getCheapestPerModel(db, 'cpu')],
	['getDealCandidates', (r, db) => r.getDealCandidates(db)],
	['getDealCandidates 60', (r, db) => r.getDealCandidates(db, 60)],
	['getMovers 7', (r, db) => r.getMovers(db, 7)],
	['getMovers 30', (r, db) => r.getMovers(db, 30)],
	['getProductMoves 7', (r, db) => r.getProductMoves(db, 7)],
	['getProductMoves 30', (r, db) => r.getProductMoves(db, 30)],
	['getComparisonData', (r, db, ids) => r.getComparisonData(db, ids.some)],
	['getComparisonData empty', (r, db) => r.getComparisonData(db, [])],
	['getProductAlerts', (r, db, ids) => r.getProductAlerts(db, ids.first)],
	['tableExists', (r, db) => [r.tableExists(db, 'products'), r.tableExists(db, 'nope')]]
];

describe('repos equivalence (#30)', () => {
	for (const [name, call] of CASES) {
		it(name, () => {
			for (const t of targets) {
				const ids = sampleIds(t.db);
				expect(normalise(call(current, t.db, ids)), `${name} on ${t.name}`).toEqual(normalise(call(legacy, t.db, ids)));
			}
		});
	}

	it('write paths produce identical rows (upsertAlert/deleteAlert)', () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'equiv-'));
		try {
			const run = (repo: any) => {
				const file = path.join(dir, `${repo === legacy ? 'legacy' : 'current'}.db`);
				fs.copyFileSync(seeded.file, file);
				const db = new Database(file);
				const id = db.prepare('SELECT id FROM products ORDER BY id LIMIT 1').get().id;
				repo.upsertAlert(db, id, 500, 'discord', true);
				repo.upsertAlert(db, id, 450, 'discord', false);
				repo.upsertAlert(db, id, 400, 'email', true);
				const toDelete = db.prepare("SELECT id FROM price_alerts WHERE channel = 'email'").get().id;
				repo.deleteAlert(db, toDelete);
				const rows = db.prepare('SELECT product_id, target_price, channel, notify_on_restock, active FROM price_alerts ORDER BY id').all();
				db.close();
				return rows;
			};
			expect(run(current)).toEqual(run(legacy));
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});
```

Read the real signatures in `repos.ts` before running: if a call shape above does not match a real signature (e.g. `getLatestListings` options, `getSparklines`/`getProductDealStats` argument), fix the CASE to the real signature — the goal is "every exported query, every argument shape a route uses". Grep the routes for each function's call sites and mirror them. If `seeded.close()` cannot run while `seeded.file` is copied, copy before closing (it is copied inside the test, before `afterAll`).

- [ ] **Step 3: Real-DB runner**

```js
// web/scripts/equivalence-real-db.mjs
// Runs test/equivalence.test.ts against a read-only TEMP COPY of the real
// local DB (never the original file: #30 data-safety rule).
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '..', '..', 'db', 'trackaroo.db');
if (!fs.existsSync(src)) {
	console.log(`No ${src}; nothing to compare against.`);
	process.exit(0);
}
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trackaroo-equiv-'));
const copy = path.join(dir, 'trackaroo.db');
fs.copyFileSync(src, copy);
for (const ext of ['-wal', '-shm']) if (fs.existsSync(src + ext)) fs.copyFileSync(src + ext, copy + ext);
try {
	execSync('npx vitest run test/equivalence.test.ts', {
		stdio: 'inherit',
		cwd: path.resolve(here, '..'),
		env: { ...process.env, TRACKAROO_EQUIV_DB: copy }
	});
} finally {
	fs.rmSync(dir, { recursive: true, force: true });
}
```

Add to `web/package.json` scripts: `"test:equiv-real": "node scripts/equivalence-real-db.mjs"`.

- [ ] **Step 4: Run — must pass trivially (current == legacy)**

From `web/`: `npx vitest run test/equivalence.test.ts` then `npm run test:equiv-real`. Expected: all pass on `seeded` and `real-copy`. Then `npm run check` (0/0) — fix type errors in the legacy copy's imports only.

- [ ] **Step 5: Baseline timings**

Build and serve against a temp copy of the real DB, measure, stop:

```bash
cd web && npm run build
cp ../db/trackaroo.db "$TMP/baseline.db"
TRACKAROO_DB="$TMP/baseline.db" PORT=3911 node server.js & SERVER=$!
sleep 4; bash scripts/measure.sh http://127.0.0.1:3911 | tee "$TMP/timings-before.txt"; kill $SERVER
```

Record the output in the task report (it is needed again in Task 7). Never point `TRACKAROO_DB` at `db/trackaroo.db` itself.

- [ ] **Step 6: Commit**

```bash
git add web/test/legacy web/test/equivalence.test.ts web/scripts/equivalence-real-db.mjs web/package.json
git commit -F - <<'MSG'
test(web): legacy-equivalence oracle for the repos.ts refactor (#30)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

---

### Task 2: Delete dead code

**Files:**
- Delete: `web/src/lib/components/LatestListingTable.svelte`, `web/src/lib/components/StatTile.svelte` and their tests
- Modify: `web/src/lib/server/repos.ts`, `web/src/lib/formats.ts`, the tests that only exercised removed code, `web/test/equivalence.test.ts` (drop CASES only for deleted functions)

- [ ] **Step 1: Prove each item is dead.** For each of `LatestListingTable`, `StatTile`, `getBrands`, `getProductSparklines`, `freshnessLabel`, the `groupListingsByProduct` sort, the `ProductGroup.sparkline`/`.deal` fields, and each `getLatestListings` filter option (`retailer`, `brand`, `tier`, `query`, `sort`): run `grep -rn "<name>" web/src web/e2e` and paste the result into the report. If anything has a non-test caller in `web/src` routes/components, **keep it** and note it.
- [ ] **Step 2: Delete** the proven-dead items and the tests that only cover them (search `web/test` for each name). For `getLatestListings`, remove only the unused options and the branches that handle them; the remaining call shape (as routes call it) must stay.
- [ ] **Step 3: Equivalence** — remove CASES only for deleted functions; all remaining CASES must pass. If a remaining CASE called `getLatestListings` with a now-removed option, change the case to the shape routes use (and in the legacy call keep the same arguments).
- [ ] **Step 4: Run** `npm run check` (0/0), `npm test`, `npm run test:e2e`, `npm run test:equiv-real`. All green.
- [ ] **Step 5: Commit** `refactor(web): remove dead components, queries and fields (#30)` (heredoc trailer).

---

### Task 3: Types to `$lib/models`, boundary guards

**Files:**
- Create: `web/src/lib/models.ts`, `web/test/boundaries.test.ts`
- Modify: `web/src/lib/server/repos.ts` (types move out; `export type * from '$lib/models'` keeps old imports working), every client file importing types from `$lib/server/repos`

**Interfaces:**
- Produces: `$lib/models` exporting every DTO interface/type currently exported by `repos.ts` (`SparklinePoint`, `PricePoint`, `LatestListing`, `ProductGroup`, `Mover`, `Series`, `PriceBandPoint`, `ProductHistory`, `TrackedProduct`, `ProductIndexEntry`, `HeaderStats`, `RetailerFreshness`, `ProductStats`, `CheapestListing`, `DealCandidate`, `ProductMove`, `ComparePrice`, `CompareEntry`, `AlertRow` — whatever remains after Task 2).

- [ ] **Step 1: Failing guard test**

```ts
// web/test/boundaries.test.ts
// #30: client code never imports server modules, and no server file grows
// past 350 lines.
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(__dirname, '..', 'src');

function walk(dir: string): string[] {
	return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
		e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]
	);
}

const files = walk(SRC).filter((f) => /\.(ts|svelte)$/.test(f));
const isServerSide = (f: string) =>
	f.includes(`${path.sep}lib${path.sep}server${path.sep}`) ||
	/\+(page|layout)\.server\.ts$/.test(f) ||
	/\+server\.ts$/.test(f) ||
	/hooks\.server\.ts$/.test(f);

describe('boundaries (#30)', () => {
	it('no client file imports $lib/server', () => {
		const offenders = files
			.filter((f) => !isServerSide(f))
			.filter((f) => /from\s+['"]\$lib\/server/.test(fs.readFileSync(f, 'utf-8')))
			.map((f) => path.relative(SRC, f));
		expect(offenders).toEqual([]);
	});
});
```

(The 350-line test is added in Task 5, when it can pass.)

- [ ] **Step 2: Run** `npx vitest run test/boundaries.test.ts` — expect FAIL listing ~11 client files.
- [ ] **Step 3: Move types.** Cut every exported `interface`/`type` from `repos.ts` into `web/src/lib/models.ts` unchanged; in `repos.ts` add `import type { ... } from '$lib/models';` for what it uses and `export type * from '$lib/models';` so server/route imports keep compiling. In each offending client file change `from '$lib/server/repos'` to `from '$lib/models'` (types only — if a client file imports a **value** from `$lib/server`, stop and report it).
- [ ] **Step 4: Run** the guard (PASS), `npm run check` (0/0), `npm test`, equivalence suite. Green.
- [ ] **Step 5: Commit** `refactor(web): DTO types in $lib/models; guard client imports (#30)`.

---

### Task 4: One SQL fragment for "daily cheapest in stock"

**Files:**
- Create: `web/src/lib/server/queries/sql.ts`
- Modify: `web/src/lib/server/repos.ts` (the five copies), `web/test/sql.test.ts` (new)

**Interfaces:**
- Produces: in `queries/sql.ts`:
  - `export function dailyCheapestInStock(opts: { windowDays: number | string; productId?: 'param' | 'join'; extraWhere?: string }): string` — returns a SQL subquery selecting `(product_id, snapshot_date, price)` = per-product per-day `MIN(price_aud)` over in-stock snapshots within the trailing window, with the bundle exclusions. Shape the options to fit the five real call sites; the signature above is a starting point, the requirement is: one function, used by all five, no behaviour change.
  - `export const BUNDLE_EXCLUSION_SQL: string` (if the copies share one exclusion clause).

- [ ] **Step 1: Inventory.** Copy the five subqueries (around `repos.ts` lines 66, 637, 662-706, 748, 883, 1240 at plan time — find them by `MIN(s.price_aud)`) into the report side by side. List every difference (window expression, joins, bundle/URL exclusions, stock condition, date anchor: `MAX(snapshot_date)` vs `date('now')`). **Any difference is preserved via an option** — never unified silently. If two copies differ in a way that looks like a bug, keep the old behaviour and report it as a finding.
- [ ] **Step 2: Unit test for the fragment** (`web/test/sql.test.ts`): build the fragment for each option set and assert it runs on the seeded DB and returns rows with columns `product_id`, `snapshot_date`, `price` (or the column names the copies use), and that a bundle-titled listing is excluded when the copy it replaces excluded it.
- [ ] **Step 3: Replace the copies one at a time.** After each replacement run `npx vitest run test/equivalence.test.ts` (seeded) — must stay green before the next one.
- [ ] **Step 4: Shared cheapest-listing builder.** Factor the ~60 identical lines of the two cheapest-listing queries (`getCheapestPerModel` and the comparable one found in Step 1's reading) into one builder in `sql.ts`; equivalence green.
- [ ] **Step 5: Real data.** `npm run test:equiv-real` — must pass. Paste the output.
- [ ] **Step 6: Run** `npm run check`, `npm test`, `npm run test:e2e`. Green.
- [ ] **Step 7: Commit** `refactor(web): one dailyCheapestInStock SQL fragment (#30)`.

---

### Task 5: Split `repos.ts` into query modules

**Files:**
- Create: `web/src/lib/server/queries/{catalog,history,stats,deals,movers,compare,alerts,health}.ts`
- Modify: `web/src/lib/server/repos.ts` (becomes a barrel), `web/test/boundaries.test.ts` (350-line guard)

- [ ] **Step 1: Failing line-count guard** — append to `boundaries.test.ts`:

```ts
	it('no server file over 350 lines', () => {
		const big = files
			.filter((f) => f.includes(`${path.sep}lib${path.sep}server${path.sep}`))
			.map((f) => [path.relative(SRC, f), fs.readFileSync(f, 'utf-8').split('\n').length] as const)
			.filter(([, n]) => n > 350);
		expect(big).toEqual([]);
	});
```

Run: FAIL (`lib/server/repos.ts` ~1,300 lines).
- [ ] **Step 2: Move functions** per the spec table (§6.4): catalog (getTrackedProducts, getLaunchDates, getProductIndex, getCategoryCounts, getAvailableCounts, getLatestListings, groupListingsByProduct, getSparklines), history (getProductHistory, getPriceBand, getRetailerLatest), stats (getProductStats, getProductDealStats, getHeaderStats), deals (getCheapestPerModel, getDealCandidates), movers (getMovers, getProductMoves), compare (getComparisonData), alerts (upsertAlert, deleteAlert, getProductAlerts), health (tableExists, getRetailerFreshness). Move private helpers with their only user; a helper used by several modules goes to `sql.ts` (SQL) or a small `queries/util.ts`. Move code **verbatim** — no edits beyond imports. Keep `discover.ts` where it is.
- [ ] **Step 3: Barrel** — `repos.ts` becomes:

```ts
// Barrel kept so existing `$lib/server/repos` imports keep working (#30).
// New code may import from $lib/server/queries/<module> directly.
export type * from '$lib/models';
export * from './queries/catalog';
export * from './queries/history';
export * from './queries/stats';
export * from './queries/deals';
export * from './queries/movers';
export * from './queries/compare';
export * from './queries/alerts';
export * from './queries/health';
```

- [ ] **Step 4: Run** guard (PASS — if a module exceeds 350 lines, split it by concern, e.g. `movers` into `movers.ts` + `moversSql.ts`), equivalence (seeded + `npm run test:equiv-real`), `npm run check`, `npm test`, `npm run test:e2e`. Green.
- [ ] **Step 5: Commit** `refactor(web): split repos.ts into query modules behind a barrel (#30)`.

---

### Task 6: One rule for "how old"

**Files:**
- Modify: `web/src/lib/formats.ts`, `web/src/routes/product/[id]/+page.svelte:~159`, `web/test/formats.test.ts`, any e2e asserting the "Updated" text

**Interfaces:**
- Produces: `updatedLabel(lastSnapshotAt: string | null, now?: Date): string` in `formats.ts`.

Rule (documented in a comment above the helpers): `daysBehindToday` + `stalenessLabel` for **date-only** values; `formatRelative` only for **true timestamps**; `updatedLabel` for the product page's "Updated …" stamp, so it agrees with the stale banner's day count.

- [ ] **Step 1: Failing tests** in `web/test/formats.test.ts`:

```ts
import { updatedLabel } from '../src/lib/formats';

describe('updatedLabel (#30)', () => {
	const now = new Date(2026, 9, 21, 14, 0); // 21 Oct 2026 14:00 local
	it('same local day: relative time', () => {
		expect(updatedLabel(new Date(2026, 9, 21, 13, 35).toISOString(), now)).toBe('Updated 25m ago');
	});
	it('earlier days: calendar days, matching the stale banner count', () => {
		expect(updatedLabel(new Date(2026, 9, 20, 23, 50).toISOString(), now)).toBe('Updated 1 day ago');
		expect(updatedLabel(new Date(2026, 9, 1, 4, 30).toISOString(), now)).toBe('Updated 20 days ago');
	});
	it('missing: never', () => {
		expect(updatedLabel(null, now)).toBe('Never updated');
	});
});
```

- [ ] **Step 2: Run** — FAIL (`updatedLabel` missing).
- [ ] **Step 3: Implement**

```ts
/**
 * The product page's "Updated ..." stamp (#30). Same local day: relative time
 * ("Updated 25m ago"). Earlier: whole calendar days, the same count the stale
 * banner uses (daysBehindToday), so the page never says "2w ago" next to
 * "20 days behind".
 */
export function updatedLabel(lastSnapshotAt: string | null, now: Date = new Date()): string {
	if (!lastSnapshotAt) return 'Never updated';
	const then = new Date(lastSnapshotAt);
	if (Number.isNaN(then.getTime())) return 'Never updated';
	const localDate = `${then.getFullYear()}-${String(then.getMonth() + 1).padStart(2, '0')}-${String(then.getDate()).padStart(2, '0')}`;
	const days = daysBehindToday(localDate, now) ?? 0;
	if (days === 0) return `Updated ${formatRelative(lastSnapshotAt, now)}`;
	return days === 1 ? 'Updated 1 day ago' : `Updated ${days} days ago`;
}
```

In `product/[id]/+page.svelte` replace `Updated {formatRelative(product.last_snapshot_at)}` with `{updatedLabel(product.last_snapshot_at)}` (adjust imports). `web/test/determinism.test.ts` forbids `toLocale*`; the code above uses none.
- [ ] **Step 4: Run** `npx vitest run test/formats.test.ts`, then `npm run check`, `npm test`, `npm run test:e2e` (update any e2e that asserted the old "Updated Xd/Xw ago" text to the new wording). Green.
- [ ] **Step 5: Commit** `fix(web): one rule for "how old"; product page Updated stamp matches the banner (#30)`.

---

### Task 7: Close-out — real-data proof, timings, remove the oracle, docs

**Files:**
- Delete: `web/test/legacy/`, `web/test/equivalence.test.ts`, `web/scripts/equivalence-real-db.mjs`, the `test:equiv-real` script
- Modify: `STATUS.md`, `CLAUDE.md` (counts; one line on `queries/` + `$lib/models`)

- [ ] **Step 1: Final proof.** `npm run test:equiv-real` and `npx vitest run test/equivalence.test.ts` on the final code; paste both outputs into the report — they go into the PR description.
- [ ] **Step 2: Timings after** — repeat Task 1 Step 5 into `$TMP/timings-after.txt`; paste before/after side by side. Any route slower by more than 20% is a finding to report, not to hide.
- [ ] **Step 3: Remove the oracle** (files above). Rationale (comment in the commit message): the legacy copy would rot; the proof is recorded in the PR.
- [ ] **Step 4: Docs.** `CLAUDE.md` Commands counts (measure: pytest, vitest, Playwright, svelte-check) and under Guardrails: "Server queries live in `web/src/lib/server/queries/*` (barrel: `$lib/server/repos`); DTO types in `$lib/models`; client code never imports `$lib/server` (`test/boundaries.test.ts`)." `STATUS.md`: dated 2026-10-02 bullet (what changed, no data/schema change, equivalence proven on seeded + real-DB copy, timings, not deployed).
- [ ] **Step 5: Full gate** — backend `python -m pytest -q`; from `web/`: `npm run check`, `npm test`, `npm run test:e2e`. All green.
- [ ] **Step 6: Commit** `chore(web): remove the #30 equivalence oracle; docs and counts`.
