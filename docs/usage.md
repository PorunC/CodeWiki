# CodeWiki Usage Guide

[Project README](../README.md) | [Architecture](typescript-backend.md) | [简体中文](README.zh-CN.md)

This guide covers the TypeScript/npm backend, runtime configuration, repository
workflows, CLI commands, Docker, and HTTP APIs for CodeWiki.

## Current Scope

- TypeScript/Fastify backend in `backend`, published as the npm package
  `codewiki-backend`.
- React/Vite frontend with repository management, graph explorer, wiki reader, ask,
  and settings pages.
- SQLite storage with the existing CodeWiki table names for repositories, analysis
  runs, graph nodes/edges, chunks, communities, and wiki pages.
- Local repository and Git URL registration, `.gitignore` handling, file tree APIs,
  and lightweight language detection.
- Deterministic lightweight graph analysis for files, definitions, imports, calls,
  source chunks, wiki drafts, and source-grounded Q&A.
- LLM environment variables are parsed and exposed by the settings API. Ask and wiki
  catalog/page flows can optionally use an OpenAI-compatible chat completion
  provider with cached runs. A stdio MCP server is included in the npm package.
  Provider-backed community generation, PostgreSQL, pgvector, and tree-sitter parity
  remain migration follow-ups.

## Installation

Install the npm package:

```bash
npm install -g codewiki-backend
codewiki --help
```

Start CodeWiki after installation:

```bash
codewiki serve
```

Then open `http://127.0.0.1:8000` for the Web UI if you are serving a build that
includes frontend assets. From a source checkout, use `make start` to run the backend
and Vite together.

## Docker

Build and run CodeWiki with Docker Compose:

```bash
docker compose up --build
```

Then open `http://127.0.0.1:8000`. The compose file persists the SQLite database and
storage cache in Docker volumes, and mounts this checkout at `/workspace/CodeWiki` so
you can register that path from the UI or CLI. To analyze another local repository,
add another bind mount under `/workspace` in `docker-compose.yml`.

## Database Configuration

CodeWiki defaults to a local SQLite database:

```bash
CODEWIKI_DATABASE_URL=sqlite:///./data/codewiki.sqlite3
```

The TypeScript backend also accepts the old Python SQLite URL spelling:

```bash
CODEWIKI_DATABASE_URL=sqlite+aiosqlite:///./data/codewiki.sqlite3
```

## Logging

HTTP server logs default to a compact readable format for local development:

```bash
CODEWIKI_LOG_LEVEL=info
CODEWIKI_LOG_FORMAT=pretty
```

Set `CODEWIKI_LOG_FORMAT=json` when forwarding logs to a structured collector.

## LLM Configuration

The TypeScript backend always supports deterministic local retrieval and wiki
drafting. Ask and wiki generation flows use local output by default, and
automatically switch to cached OpenAI-compatible chat completions when a matching
LLM profile is configured:

```bash
CODEWIKI_LLM__MODE=sdk
CODEWIKI_LLM__DEFAULT__MODEL=provider/strong-coding-model
CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE=
CODEWIKI_LLM__DEFAULT__ENDPOINT=
CODEWIKI_LLM__DEFAULT__API_KEY=
CODEWIKI_LLM__DEFAULT__MAX_TOKENS=

CODEWIKI_LLM__PROFILES__QA__MODEL=
CODEWIKI_LLM__PROFILES__QA__API_KEY=

CODEWIKI_LLM__PROFILES__CATALOG__MODEL=
CODEWIKI_LLM__PROFILES__CATALOG__API_KEY=
CODEWIKI_LLM__PROFILES__PAGE__MODEL=
CODEWIKI_LLM__PROFILES__PAGE__API_KEY=
```

## Repository Workflow

```bash
codewiki repos add . --name my-repo
codewiki analyze my-repo
codewiki wiki catalog my-repo
codewiki wiki pages my-repo
codewiki ask "How does the main workflow fit together?" my-repo
```

Most repository arguments accept an id, id prefix, registered name, path, or Git URL.
Use `--json` on CLI commands when machine-readable output is useful.

## Development

```bash
# Install backend and frontend dependencies
make install

# Start the TypeScript backend and Vite
make start

# Stop local dev servers on the configured ports
make kill
```

Default local URLs:

- TypeScript backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

Useful checks:

```bash
make lint
make typecheck
make test
make test-scripts
make lint-scripts
make build
make npm-pack
make npm-smoke
```

## npm Package

The publishable package lives in `backend`:

```bash
cd backend
npm run verify
npm run build
npm pack --dry-run
npm run pack:smoke
```

Package entrypoints:

- CLI binaries: `codewiki`, `codewiki-backend`
- MCP binary: `codewiki-mcp`
- Library export: `codewiki-backend`
- Server export: `codewiki-backend/server`
- MCP export: `codewiki-backend/mcp`

## MCP

The npm package includes a stdio MCP server:

```bash
codewiki-mcp
```

It exposes local repository, analysis, graph, GraphRAG context, wiki, and ask
tools backed by the TypeScript services and the configured SQLite database.

## CLI

```bash
# Register or inspect repositories
codewiki repos add . --name my-repo
codewiki repos list
codewiki repos scan .

# Analyze and build local graph/chunk data
codewiki analyze my-repo

# Wiki generation
codewiki wiki catalog my-repo
codewiki wiki pages my-repo
codewiki wiki list my-repo --json
codewiki wiki read overview my-repo

# Source-grounded local Q&A
codewiki ask "Where are wiki pages generated?" my-repo

# Serve HTTP API and frontend assets
codewiki serve --host 127.0.0.1 --port 8000
```

## HTTP API Highlights

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/repos` | Register a local path or Git URL |
| `GET` | `/api/repos` | List repositories |
| `GET` | `/api/repos/{repo_id}/files` | Read live repository files and tree |
| `POST` | `/api/repos/{repo_id}/analyze` | Run TypeScript graph analysis |
| `GET` | `/api/repos/{repo_id}/graph` | Read graph nodes, edges, and communities |
| `GET` | `/api/repos/{repo_id}/graph/search?q=...` | Search indexed nodes |
| `GET` | `/api/repos/{repo_id}/graph/status` | Read graph status summary |
| `POST` | `/api/repos/{repo_id}/wiki/catalog?language=en` | Generate a local or provider-backed wiki catalog |
| `POST` | `/api/repos/{repo_id}/wiki/pages/generate?language=en` | Generate wiki pages |
| `GET` | `/api/repos/{repo_id}/wiki?language=en` | Read wiki catalog and pages |
| `POST` | `/api/repos/{repo_id}/ask` | Ask a source-grounded local question |

## Notes

The current TypeScript graph analyzer intentionally favors a small dependency surface
and npm publishability. It uses lightweight parsing heuristics now, while keeping the
database shape and HTTP payloads aligned with the previous backend so deeper parser,
LLM, and vector-search migrations can continue incrementally.
