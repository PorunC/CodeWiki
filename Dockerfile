ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${NODE_IMAGE} AS frontend-builder
ARG NPM_REGISTRY=
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm --prefix frontend ci --loglevel=info --fetch-timeout=120000 --fetch-retries=5
COPY frontend ./frontend
RUN npm --prefix frontend run build

FROM ${PYTHON_IMAGE} AS python-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    CODEWIKI_SKIP_FRONTEND_BUILD=1

COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

WORKDIR /build

COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY backend ./backend
COPY --from=frontend-builder /app/backend/app/static ./backend/app/static

RUN pip install --upgrade pip \
    && pip wheel --wheel-dir /wheels .

FROM ${PYTHON_IMAGE} AS runtime-base

ARG APT_MIRROR=
ARG APT_SECURITY_MIRROR=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    CODEWIKI_DATABASE_URL=sqlite+aiosqlite:////app/data/codewiki.sqlite3 \
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
        libpq5 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

FROM runtime-base AS runtime

WORKDIR /app

COPY --from=python-builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels codewiki \
    && rm -rf /wheels

RUN mkdir -p /app/data /app/storage /workspace

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
