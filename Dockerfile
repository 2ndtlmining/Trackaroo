# Trackaroo — all-in-one image (Python pipeline + SvelteKit dashboard).
#
# One container runs everything: it serves the dashboard on :3000 and runs the
# daily scrape → ingest → mirror → health-check → backup pipeline. There is no
# docker-compose — plain `docker run` is the supported way to run this.
#
# Build from the repo root (not web/):
#   docker build -t trackaroo .
#
# Run, mapping the DB and snapshots onto the host so data outlives the
# container (bash/Linux; see README.md for the PowerShell form):
#   docker run -d --name trackaroo -p 3000:3000 --restart unless-stopped --env-file .env -v "$(pwd)/db:/app/db" -v "$(pwd)/data:/app/data" trackaroo
#
# Those two mounts matter: without them the SQLite DB and the JSON snapshots
# live in the container's writable layer and are destroyed by `docker rm`.
#
# One-shot pipeline run (no scheduler; exits when the run finishes):
#   docker run --rm -e RUN_ONCE=1 -v "$(pwd)/db:/app/db" -v "$(pwd)/data:/app/data" trackaroo
#
# Pipeline only, no dashboard (override the entrypoint):
#   docker run -d --name trackaroo-pipeline -v "$(pwd)/db:/app/db" -v "$(pwd)/data:/app/data" --entrypoint /usr/bin/tini trackaroo -- /usr/local/bin/trackaroo-entrypoint-pipeline
#
# Dashboard only, no pipeline:
#   docker run -d --name trackaroo-web -p 3000:3000 -v "$(pwd)/db:/app/db" --entrypoint /usr/bin/tini trackaroo -- node web/server.js

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
    && apt-get install -y --no-install-recommends tini bash tzdata \
    && rm -rf /var/lib/apt/lists/*

# Node runtime binary (matchest the node:24 stage the frontend was built with).
COPY --from=web /usr/local/bin/node /usr/local/bin/node

# TZ matters for correctness, not cosmetics: the scrapers stamp snapshots with
# date.today(), so a UTC container running at 07:40 AEST would file the data
# under the previous day and silently fork the history.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    TZ=Australia/Melbourne \
    TRACKAROO_DATA_DIR=/app/data \
    TRACKAROO_DB=/app/db/trackaroo.db \
    TRACKAROO_BACKUP_DIR=/app/db/backups

WORKDIR /app

# Python backend — install deps first (layer caching), then app code.
COPY requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY *.py ./
COPY scraper/ scraper/
COPY db/ db/
# Snapshot history so a fresh DB isn't empty on first boot.
COPY data/ ./seed-data/
COPY deploy/entrypoint.sh /usr/local/bin/trackaroo-entrypoint-pipeline
COPY deploy/entrypoint-single.sh /usr/local/bin/trackaroo-entrypoint
COPY deploy/bootstrap-data.sh /usr/local/bin/trackaroo-bootstrap-data

# Belt and braces on line endings. .gitattributes pins *.sh to eol=lf, but a
# source zip, an old clone, or a stray editor can still deliver CRLF -- and a
# carriage return on the shebang makes the kernel hunt for an interpreter
# literally named "/bin/sh\r", then fail with
#   exec /usr/local/bin/trackaroo-entrypoint: no such file or directory
# which reads as a missing COPY rather than a line-ending problem. Stripping
# here means a broken checkout cannot produce a container that will not boot.
# sh -n parses each script without running it, so a syntax error fails the
# build instead of the first boot.
RUN set -eux; \
    for f in trackaroo-entrypoint trackaroo-entrypoint-pipeline trackaroo-bootstrap-data; do \
        sed -i 's/\r$//' "/usr/local/bin/$f"; \
        chmod +x "/usr/local/bin/$f"; \
        sh -n "/usr/local/bin/$f"; \
    done

# Web frontend runtime bits built in stage 1.
COPY --from=web /app/web/node_modules ./web/node_modules
COPY --from=web /app/web/build ./web/build
COPY --from=web /app/web/server.js ./web/server.js
COPY --from=web /app/web/package.json ./web/package.json
COPY --from=web /app/web/svelte.config.js ./web/svelte.config.js

# db/ and data/ are bind-mounted (or volume-mounted) at runtime; the code just
# needs the dirs to exist so an unmounted `docker run` still works.
RUN mkdir -p /app/db/backups /app/data

# Build stamp (#9, #3): what is actually running shows in /healthz.
#   docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t trackaroo .
# Declared last so a new SHA only rebuilds this layer.
ARG GIT_SHA=dev
ENV TRACKAROO_VERSION=$GIT_SHA

# /healthz answers 200 once node is up and the DB opens. start-period covers a
# first boot that hydrates the whole snapshot history before node starts.
# Docker only *reports* unhealthy (docker ps); restarting on it needs autoheal
# or an external monitor (Phase 6).
HEALTHCHECK --interval=30s --timeout=5s --start-period=5m --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/healthz').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"

EXPOSE 3000

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/trackaroo-entrypoint"]