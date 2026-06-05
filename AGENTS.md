# Repository Guidelines

## Project Structure & Module Organization
- `backend/src/`: TypeScript backend, CLI, HTTP server, MCP server, and core services (`analysis/`, `graph/`, `graphrag/`, `wiki/`, `scanner/`).
- `backend/src/http/`: Fastify HTTP routes and server setup.
- `backend/src/db/`: SQLite schema, repositories, and persistence helpers.
- `frontend/src/`: React + TypeScript UI (`pages/`, `api/`, `graph/`, `wiki/`, `ask/`, `styles/`).
- `backend/test/`: Vitest suite for backend services, CLI, MCP, and API behavior.
- `tests/scripts/`: pytest coverage for Python utility scripts.
- `docs/`: usage, architecture, benchmarking, and release notes. `scripts/`: local dev utilities.

## Build, Test, and Development Commands
- `make install`: install TypeScript backend and frontend npm dependencies.
- `make dev` (or `make start`): run the TypeScript backend on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`.
- `make backend` / `make frontend`: run one side only.
- `make test`: run backend tests via Vitest.
- `make test-scripts`: run pytest coverage for Python utility scripts.
- `make lint`: run backend and frontend ESLint checks.
- `make lint-scripts`: run Ruff checks for Python utility scripts.
- `make build`: build the TypeScript backend and frontend.
- `make kill`: stop processes on dev ports.

## Coding Style & Naming Conventions
- Python utility scripts: target `py312`, max line length 100, lint with Ruff. Use `snake_case` for modules/functions, `PascalCase` for classes.
- TypeScript/React: ESLint + TypeScript checks; components in `PascalCase` files (for example `GraphPage.tsx`), hooks prefixed with `use` (for example `useRepoGraph.ts`).
- Keep modules focused by domain (graph, wiki, ask, db) and colocate helpers with the feature directory.

## TypeScript Typing Guidelines
- Run `make typecheck` when changing backend TypeScript paths.
- Add explicit types for exported service, repository, CLI, MCP, HTTP helper, and shared utility APIs.
- Prefer domain interfaces, discriminated unions, and focused payload types over broad `Record<string, unknown>` when values cross module boundaries.
- Keep `unknown` at integration edges only, such as JSON payloads, process output parsing, and third-party package responses.
- Avoid type assertions unless the invariant is checked nearby; add a short comment when the reason is not obvious.

## Architecture & Responsibility Boundaries
- Apply responsibility separation across the whole project, not only to a specific file or interface. Each module should have one clear reason to change and should avoid mixing transport, orchestration, domain logic, persistence, formatting, and configuration concerns.
- Keep entrypoints thin across all transports and runtimes. CLI commands, MCP handlers, Fastify routes, frontend API wrappers, scripts, and build hooks should parse inputs, call focused services, format outputs, and handle transport-specific errors only.
- Put business workflows in focused service modules under `backend/src/services/` and domain packages; keep persistence in `backend/src/db/` repositories; keep HTTP schemas, MCP tool schemas, CLI options, and frontend types at their respective boundaries.
- Extract shared behavior instead of duplicating it across interfaces. Repo selector resolution, JSON/dataclass serialization, graph status summaries, command/tool/API payload shaping, and validation helpers should live in reusable modules when used by more than one boundary.
- Split large modules before adding new feature families. Prefer domain-oriented packages and small files over growing entrypoints, service modules, API routes, or frontend components past a coherent responsibility.
- Keep protocol and framework concerns separate from domain concerns. JSON-RPC framing, HTTP request handling, Click command wiring, React state/rendering, and build tooling should not directly own graph/wiki/GraphRAG business rules.
- Add or update tests at the boundary being changed: service tests for shared workflows, repository tests for persistence, CLI tests for command wiring/output, MCP tests for tool schemas and JSON-RPC behavior, API tests for HTTP routes, and frontend tests/build checks for UI behavior.

## Testing Guidelines
- Frameworks: Vitest for `backend/test/`; pytest only for Python utility scripts under `tests/scripts/`.
- Prefer focused unit tests per service/module, with API/CLI/MCP coverage for user-facing backend flows.
- Run `make test` before opening a PR; run `make test-scripts` and `make lint-scripts` when changing Python utility scripts. Add regression tests for bug fixes.

## Commit & Pull Request Guidelines
- Follow Conventional Commit style seen in history: `feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`.
- Keep commit scope specific (`backend`, `frontend`, `wiki`, `graphrag`, etc.).
- PRs should include: purpose, key changes, test/lint results, linked issues, and screenshots/GIFs for UI changes.

## Environment & Configuration Tips
- Node.js 22 is required for the TypeScript backend.
- Python 3.12 is only needed for local utility scripts and their pytest coverage.
- Copy `.env.example` to configure local settings and LLM provider variables.
- Use `codewiki` CLI for local workflows, e.g. `codewiki analyze .` and `codewiki ask "..."`.
