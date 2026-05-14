# Repository Guidelines

## Project Structure & Module Organization
- `backend/app/`: FastAPI app, CLI, and core services (`graph/`, `graphrag/`, `wiki/`, `incremental/`, `repo_scanner/`).
- `backend/app/api/`: HTTP routes (`ask`, `wiki`, `graph`, `repos`, `files`, `runs`, `settings`).
- `backend/app/db/`: SQLAlchemy schema, repositories, and persistence helpers.
- `frontend/src/`: React + TypeScript UI (`pages/`, `api/`, `graph/`, `wiki/`, `ask/`, `styles/`).
- `tests/backend/`: pytest suite for backend services, CLI, and API behavior.
- `docs/`: design and architecture notes. `scripts/`: local dev utilities (for example `kill_ports.py`).

## Build, Test, and Development Commands
- `make install`: install backend (`pip install -e ".[dev]"`) and frontend deps.
- `make dev` (or `make start`): run FastAPI on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`.
- `make backend` / `make frontend`: run one side only.
- `make test`: run backend tests via `pytest -q`.
- `make lint`: run `ruff check backend tests` and frontend `eslint`.
- `make build`: type-check and build frontend (`tsc -b && vite build`).
- `make kill`: stop processes on dev ports.

## Coding Style & Naming Conventions
- Python: target `py312`, max line length 100, lint with Ruff. Use `snake_case` for modules/functions, `PascalCase` for classes.
- TypeScript/React: ESLint + TypeScript checks; components in `PascalCase` files (for example `GraphPage.tsx`), hooks prefixed with `use` (for example `useRepoGraph.ts`).
- Keep modules focused by domain (graph, wiki, ask, db) and colocate helpers with the feature directory.

## Testing Guidelines
- Framework: `pytest` with tests under `tests/backend/` and files named `test_*.py`.
- Prefer focused unit tests per service/module, with API/CLI coverage for user-facing flows.
- Run `make test` before opening a PR; add regression tests for bug fixes.

## Commit & Pull Request Guidelines
- Follow Conventional Commit style seen in history: `feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`.
- Keep commit scope specific (`backend`, `frontend`, `wiki`, `graphrag`, etc.).
- PRs should include: purpose, key changes, test/lint results, linked issues, and screenshots/GIFs for UI changes.

## Environment & Configuration Tips
- Python 3.12 is required (`make` enforces it).
- Copy `.env.example` to configure local settings and LLM provider variables.
- Use `codewiki` CLI for local workflows, e.g. `codewiki analyze .` and `codewiki ask "..."`.
