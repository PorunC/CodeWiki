# CodeWiki

<p align="center">
  <strong>English</strong>
  &nbsp;·&nbsp;
  <a href="./docs/README.zh-CN.md">简体中文</a>
  &nbsp;·&nbsp;
  <a href="./docs/usage.md">Usage Guide</a>
  &nbsp;·&nbsp;
  <a href="./docs/design.md">Design</a>
  &nbsp;·&nbsp;
  <a href="./docs/benchmarking.md">Benchmarks</a>
  &nbsp;·&nbsp;
  <a href="./docs/changelog.md">Changelog</a>
</p>

<p align="center">
  <a href="https://github.com/PorunC/CodeWiki/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/PorunC/CodeWiki/test.yml?style=flat-square&label=tests&labelColor=161b22&logo=githubactions&logoColor=white" alt="Tests"/></a>
  <a href="./LICENSE"><img src="https://img.shields.io/github/license/PorunC/CodeWiki?style=flat-square&color=8b949e&labelColor=161b22" alt="License"/></a>
  <a href="https://pepy.tech/projects/codewiki"><img src="https://static.pepy.tech/personalized-badge/codewiki?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads" alt="PyPI downloads"/></a>
  <a href="https://github.com/PorunC/CodeWiki/stargazers"><img src="https://img.shields.io/github/stars/PorunC/CodeWiki.svg?style=flat-square&color=dbab09&labelColor=161b22&logo=github&logoColor=white" alt="GitHub stars"/></a>
</p>

CodeWiki is a single-user code intelligence platform for AST-based repository analysis,
GraphRAG retrieval, source-grounded wiki generation, and LiteLLM-powered Q&A.

## Screenshots

![CodeWiki wiki page](docs/img/wiki.png)

![CodeWiki graph explorer](docs/img/graph.png)

## Highlights

- Analyze Python, TypeScript/TSX, JavaScript/JSX, Java, Go, Rust, C, C++, and C#.
- Build deterministic code graphs for imports, definitions, calls, routes, inheritance,
  source references, and configuration usage.
- Generate DeepWiki-style catalogs and pages with source citations, diagrams,
  translations, incremental updates, and browser-side exports.
- Ask GraphRAG-grounded questions through the Web UI, CLI, HTTP API, or MCP server.
- Use Lite Mode for a project-local, no-LLM graph index optimized for AI agent context,
  traces, impact analysis, and MCP tools.
- Use SQLite by default, or PostgreSQL with full-text search and optional pgvector
  vector search.

## Quick Start

Install from PyPI:

```bash
pip install codewiki
codewiki serve
```

Open `http://127.0.0.1:8000`, register a repository, run analysis, then generate a
wiki or ask questions.

Run with Docker Compose:

```bash
docker compose up --build
```

The packaged Python app includes the built frontend. A source checkout is only needed
for development or Docker-based local runs.

## Common Commands

```bash
codewiki repos add . --name my-repo
codewiki analyze .
codewiki graphrag build . --embeddings
codewiki wiki catalog .
codewiki wiki pages .
codewiki ask --repo my-repo "How does the main workflow fit together?"
codewiki mcp
```

Most repository arguments accept an id, id prefix, registered name, path, or Git URL.
Use `--json` for machine-readable output.

### Lite Mode

Lite Mode creates a project-local `.codewiki/codewiki-lite.sqlite3` index and skips
LLM, Wiki, GraphRAG chunk, and Web UI workflows. It is intended for local AI assistants
that need fast symbol search, source context, call traces, and affected-file analysis.

```bash
codewiki lite index .
codewiki lite query AuthService
codewiki lite context "how authentication works"
codewiki lite trace LoginForm createSession
codewiki lite callers generate_page
codewiki lite affected src/auth.py
codewiki lite agents install . --target all
codewiki mcp --lite --path .
```

`codewiki lite status` reports pending file changes. `codewiki lite sync` refreshes the
index, and `codewiki lite watch` keeps it fresh with a polling watcher. MCP Lite Mode
catches up an existing index on startup unless `--no-sync` is passed.
`codewiki lite agents install` can write Codex CLI and Claude Code MCP config plus
agent instructions for the project.

## Configuration

CodeWiki defaults to SQLite:

```bash
CODEWIKI_DATABASE_URL=sqlite+aiosqlite:///./data/codewiki.sqlite3
```

PostgreSQL is also supported:

```bash
CODEWIKI_DATABASE_URL=postgresql+psycopg://codewiki:codewiki@localhost:5432/codewiki
```

Configure LLM profiles with `codewiki config` or `.env`:

```bash
codewiki config
codewiki config --set CODEWIKI_LLM__DEFAULT__MODEL=openai/gpt-4.1
codewiki config --profile qa --model openai/gpt-4.1 --api-key "$OPENAI_API_KEY"
```

## Documentation

- [Usage Guide](docs/usage.md): installation, Docker, database setup, wiki workflow,
  LLM profiles, CLI, MCP, HTTP API, and supported languages.
- [Design Notes](docs/design.md): architecture and feature design.
- [PostgreSQL Compatibility Design](docs/postgres-compatibility-design.md): storage
  compatibility, PostgreSQL FTS, and pgvector design.
- [Benchmarking Guide](docs/benchmarking.md) and
  [Benchmark Report](docs/benchmark-report-2026-05-22.md): benchmark workflow and
  current results.
- [Changelog](docs/changelog.md): release history.

## Development

```bash
make install
make start
make lint
make typecheck
make test
make build
```

Default local URLs:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

### Python Typing

Python type checking uses `mypy` with a gradual configuration in `pyproject.toml`.
New public service, repository, API helper, and CLI helper functions should include
explicit parameter and return types. Prefer dataclasses, Pydantic models, `TypedDict`,
or `Protocol` over broad `dict[str, Any]` when data crosses module boundaries. Keep
`Any` near integration edges such as LLM JSON payloads, SQLAlchemy JSON columns, and
third-party parser output.

## License

MIT
