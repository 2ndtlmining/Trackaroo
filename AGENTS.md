# Trackaroo — Agent Guide

Monorepo: Python scraper + ingest at the repo root, SvelteKit frontend in `web/`.

## Commands (run from `web/`)

- **Unit tests**: `npm test` (Vitest, 154 tests, ~2s)
- **Watch mode**: `npm run test:watch`
- **E2E tests**: `npm run test:e2e` (Playwright, Chromium only, must be kept fast)
  - Runs against a deterministic seeded DB (`e2e/seed.mjs` → `e2e/e2e.db`) served by a `vite dev` server on port 4174.
  - `e2e.db`, `test-results/`, and `playwright-report/` are gitignored and regenerated on each run.
- **Type + Svelte check**: `npm run check` (svelte-check, must report 0 errors)
- **Full validation before finishing a task**: backend `python -m pytest -q` (391 tests, run from the repo root), then from `web/`: `npm run check`, `npm test`, then `npm run test:e2e`.
- **Build**: `npm run build` (svelte-kit sync + vite build; run if a change affects the production build).

## Docker (from the repo root, NOT `web/`)

- The **single all-in-one image** is the primary deployment: Python pipeline +
  SvelteKit dashboard in one container. Build + run:
  ```bash
  docker build -t trackaroo .            # context = repo root
  docker run -d --name trackaroo -p 3000:3000 -v trackaroo-data:/data trackaroo
  ```
- `deploy/entrypoint-single.sh` seeds the DB, starts the dashboard (:3000) and
  runs the pipeline every `RUN_INTERVAL_HOURS` (default 24), plus the weekly
  spec sync (`sync_specs.py`) at `SPEC_SYNC_DOW` @ `SPEC_SYNC_HOUR` (default
  Sunday 03:00). `RUN_ONCE=1` runs one pipeline then exits.
- `docker-compose.yml` is the optional two-service split of the SAME image
  (`cron` pins the pipeline-only entrypoint, `web` runs the server).
- Critical constraint: the app NEEDS Python 3.12 (PEP 701 f-strings like
  `f"{wp["vram_gb"]}gb"` are compile errors on 3.11) — so the runtime stage is
  based on `python:3.12-slim` with the Node binary copied from the build stage.
  Never switch the runtime to apt/bookworm `python3`.

## E2E conventions

- **Interaction hydration race**: The app is server-rendered; clicks/selects can land before Svelte hydrates and silently do nothing. Every page navigation in `e2e/app.spec.ts` must go through the local `goto()` helper, which waits for `networkidle` (i.e. hydration done) before the test interacts:
  ```ts
  async function goto(page: Page, path: string) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
  }
  ```
  Do **not** call `page.goto(...)` directly in specs; use `goto(page, path)` (and `await page.waitForLoadState('networkidle')` after `page.reload()`).
- Keep the suite deterministic: it asserts against fixed seeded data, so assertions must not depend on scraped-live data.
- Keep the suite fast (goal ≲ 60s). Avoid artificial `waitForTimeout` sleeps.

## Guardrails

- Never commit secrets or `.env` values. `.env.example` is the template.
- Generated/regenerable files (`web/e2e/e2e.db`, Playwright artifacts) must stay gitignored.