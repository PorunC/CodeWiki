# syntax=docker/dockerfile:1.7

FROM node:22-slim AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm --prefix frontend ci
COPY frontend ./frontend
RUN npm --prefix frontend run build

FROM python:3.12-slim AS python-builder

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

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    CODEWIKI_DATABASE_URL=sqlite+aiosqlite:////app/data/codewiki.sqlite3 \
    CODEWIKI_STORAGE_DIR=/app/storage

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=python-builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels codewiki \
    && rm -rf /wheels

RUN mkdir -p /app/data /app/storage /workspace

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
