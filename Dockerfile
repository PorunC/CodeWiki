ARG NODE_IMAGE=node:22-bookworm-slim

FROM ${NODE_IMAGE} AS frontend-builder
ARG NPM_REGISTRY=
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm --prefix frontend ci --loglevel=info --fetch-timeout=120000 --fetch-retries=5
COPY frontend ./frontend
RUN npm --prefix frontend run build

FROM ${NODE_IMAGE} AS backend-builder
ARG NPM_REGISTRY=
WORKDIR /app
RUN apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        python3 \
    && rm -rf /var/lib/apt/lists/*
COPY backend-ts/package.json backend-ts/package-lock.json ./backend-ts/
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm --prefix backend-ts ci --loglevel=info --fetch-timeout=120000 --fetch-retries=5
COPY backend-ts ./backend-ts
RUN npm --prefix backend-ts run build \
    && npm --prefix backend-ts prune --omit=dev

FROM ${NODE_IMAGE} AS runtime

ARG APT_MIRROR=
ARG APT_SECURITY_MIRROR=

ENV NODE_ENV=production \
    DEBIAN_FRONTEND=noninteractive \
    CODEWIKI_DATABASE_URL=sqlite:////app/data/codewiki.sqlite3 \
    CODEWIKI_STORAGE_DIR=/app/storage

RUN if [ -n "$APT_MIRROR" ]; then \
        security_mirror="${APT_SECURITY_MIRROR:-${APT_MIRROR%-security}-security}"; \
        sed -i \
            -e "s|http://deb.debian.org/debian-security|${security_mirror}|g" \
            -e "s|http://deb.debian.org/debian|${APT_MIRROR}|g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=backend-builder /app/backend-ts/package.json ./backend/package.json
COPY --from=backend-builder /app/backend-ts/dist ./backend/dist
COPY --from=backend-builder /app/backend-ts/node_modules ./backend/node_modules
COPY --from=frontend-builder /app/backend-ts/static ./static

RUN mkdir -p /app/data /app/storage /workspace

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:8000/api/health').then(r => { if (!r.ok) process.exit(1); }).catch(() => process.exit(1))"

CMD ["node", "/app/backend/dist/cli.js", "serve", "--host", "0.0.0.0", "--port", "8000", "--static-dir", "/app/static"]
