# TypeScript Backend Architecture

This document describes the current CodeWiki backend in `backend`. It is the
default runtime for local development, Docker, CI, MCP, CLI, and npm publishing.
The previous backend implementation has been removed from the active source tree.

## Runtime Shape

```text
Repository path or Git URL
  -> RepoScanner
       git clone/metadata, ignore rules, file metadata, language detection
  -> AnalysisService
       RepositoryGraphBuilder, source parser, graph chunks, communities
  -> CodeWikiStore
       SQLite repositories, runs, graph, chunks, retrieval traces, wiki pages
  -> BackendServices
       AnalysisService, GraphRAGService, WikiService, QuestionAnswerer
       deterministic retrieval, optional cached LLM answers, wiki catalogs/pages
  -> Fastify HTTP API / Commander CLI / stdio MCP server
  -> React/Vite frontend and editor agents
```

The package is published from `backend` as `code-wiki`. Runtime entry
points are:

- CLI binaries: `codewiki`, `codewiki-backend`
- MCP binary: `codewiki-mcp`
- Library exports: `code-wiki`, `code-wiki/server`, `code-wiki/mcp`

## Module Boundaries

The backend keeps transport, orchestration, persistence, and domain logic in
separate packages:

| Area | Path | Responsibility |
|---|---|---|
| HTTP transport | `src/http` | Fastify server setup, request validation, route registration, static frontend serving |
| CLI transport | `src/cli` and `src/cli.ts` | Commander commands, output formatting, database override wiring |
| MCP transport | `src/mcp` | JSON-RPC protocol handling, tool schemas, stdio entrypoint |
| Persistence | `src/db` | SQLite schema setup and repositories for repos, runs, graph, traces, wiki pages |
| Scanning | `src/scanner` | Local/Git repo description, ignore handling, file metadata, hashes, language detection |
| Analysis | `src/analysis` | Deterministic graph building, source parsing, relationships, chunks, communities |
| Graph operations | `src/graph` | Search, status, impact, affected files, node context, community payloads |
| GraphRAG | `src/graphrag` | Retrieval, context packs, retrieval trace persistence |
| Wiki | `src/wiki` | Local and provider-backed catalogs/pages, update flows, translation copy workflow |
| Service runtime | `src/services` | Repo selection helpers and shared service construction for transports |
| Lite mode | `src/lite*` | Project-local `.codewiki` database and lightweight MCP/CLI flows |

Transport layers are intentionally thin. They parse input, resolve repository
selectors, call focused services, and shape output. Shared workflows such as repo
selection, graph operations, retrieval payloads, and wiki generation live outside
the transport folders.

## Dependency Ownership

Services receive their dependencies explicitly. This keeps the npm library surface
predictable for embedding and testing:

- `AnalysisService` receives a `CodeWikiStore` and `RepoScanner`.
- `createBackendServices()` and `createBackendRuntime()` compose the shared
  service set used by HTTP, CLI, MCP, and Lite flows.
- `createServer()` can receive external `settings`, `store`, `scanner`, and
  service implementations.
  A store created by `createServer()` is closed with the Fastify app; an external
  store remains owned by the caller.
- `CodeWikiMCPServer` can receive external `settings`, `store`, `scanner`, and
  service implementations. It only closes a store it created itself.
- MCP tools are built from an explicit runtime object and do not construct
  stores, scanners, or domain services internally.
- CLI commands and HTTP routes use the same service runtime instead of
  constructing domain services in transport handlers.

The runtime version is read from `backend/package.json` through
`src/version.ts`, and the same value is used by the CLI, MCP server info, and main
library export.

## Storage

The TypeScript backend currently targets SQLite and keeps the established CodeWiki
table names where practical. `CodeWikiStore` owns schema initialization and composes
small repository classes:

- `RepoRepository`
- `AnalysisRunRepository`
- `GraphRepository`
- `RetrievalTraceRepository`
- `WikiRepository`

The TypeScript runtime accepts both `sqlite:///...` and the older
`sqlite+aiosqlite:///...` URL spelling so existing local SQLite configuration keeps
working.

## Package And CI

The npm package is built and verified from `backend`:

```bash
npm --prefix backend run verify
npm --prefix backend run build
npm --prefix backend run pack:smoke
```

`pack:smoke` creates an npm tarball, installs it into a clean temporary project,
and verifies:

- CLI binaries and version output
- repository registration, analysis, wiki, GraphRAG, and Lite CLI workflows
- library exports, shared service runtime exports, and runtime version export
- release version verifier packaging and execution
- packaged static frontend serving and API 404 behavior
- stdio MCP entrypoints and required tool registration

GitHub Actions uses Node 22 and publishes `backend` to npm on version tags.
The publish workflow independently runs backend verification, frontend linting,
release-version validation, and package smoke tests before `npm publish`.

## Current Boundaries

The current TypeScript backend intentionally favors a small dependency surface and
publishable npm package. Some deeper capabilities remain future work rather than
default runtime requirements:

- provider-backed community generation and embeddings
- PostgreSQL and pgvector storage
- tree-sitter-backed parser depth beyond the current lightweight analysis
- richer incremental update planning

The root `pyproject.toml` is limited to Python utility-script test configuration and
does not define a Python package, build backend, or `codewiki` console scripts.
The only publishable backend package is `backend/package.json`.
