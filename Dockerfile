# Trackaroo — all-in-one image (Python pipeline + SvelteKit dashboard).
#
# Build from the repo root (not web/):
#   docker build -t trackaroo .
# Run:
#   docker run -d --name trackaroo -p 3000:3000 \
#     -v trackaroo-data:/data \
#     trackaroo
#
# The single runtime container seeds/uses the SQLite DB in /data, serves the
# dashboard on :3000, and runs the scrape→ingest→backup pipeline every
# RUN_INTERVAL_HOURS (default 24). No docker-compose required.

# ── Stage 1: build the SvelteKit frontend ──────────────────────────────────
FROM node:24-bookworm-slim AS web

WORKDIR /app/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build
# Drop dev deps so the runtime image stays lean (better-sqlite3 native module
# must remain in node_modules).
RUN npm prune --omit=dev

# ── Stage 2: runtime ───────────────────────────────────────────────────────
# python:3.12-slim so the scrapers' PEP 701 f-strings (f"{x["key"]}") work
# (bookworm's apt python3 is 3.11). The Node web runtime is copied in from the
# build stage binary — no npm needed at runtime.
FROM python:3.12-slim

# Tini gives the container a sane init; bash keeps the entrypoint simple.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini bash \
    && rm -rf /var/lib/apt/lists/*

# Node runtime binary (matchest the node:24 stage the frontend was built with).
COPY --from=web /usr/local/bin/node /usr/local/bin/node

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    TRACKAROO_DATA_DIR=/data \
    TRACKAROO_DB=/data/trackaroo.db \
    TRACKAROO_BACKUP_DIR=/data/backups

WORKDIR /app

# Python backend — install deps first (layer caching), then app code.
COPY requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY *.py ./
COPY scraper/ scraper/
COPY db/ db/
COPY deploy/entrypoint.sh /usr/local/bin/trackaroo-entrypoint-pipeline
COPY deploy/entrypoint-single.sh /usr/local/bin/trackaroo-entrypoint

# Web frontend runtime bits built in stage 1.
COPY --from=web /app/web/node_modules ./web/node_modules
COPY --from=web /app/web/build ./web/build
COPY --from=web /app/web/package.json ./web/package.json
COPY --from=web /app/web/svelte.config.js ./web/svelte.config.js

# The DB lives on a mounted volume; the code just needs the dir to exist.
RUN mkdir -p /data

EXPOSE 3000

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/trackaroo-entrypoint"]