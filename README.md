# CodeWiki

[简体中文](docs/README.zh-CN.md)

Single-user CodeWiki platform for AST-based code graph analysis, GraphRAG retrieval,
source-grounded wiki generation, and LiteLLM-powered Q&A.

## Current Scope

- FastAPI backend with repository management, analysis runs, GraphRAG, wiki, ask, graph,
  file, run, and settings APIs.
- React/Vite frontend with repository management plus graph explorer, wiki reader,
  ask, and settings pages.
- AST-backed code graph extraction for Python, TypeScript/TSX, JavaScript/JSX, Java,
  Go, Rust, C, C++, and C#.
- Deterministic graph edges for imports, exports, definitions, inheritance,
  implementations, calls, route handlers, source references, and configuration usage.
- GraphRAG retrieval with source chunks, optional embeddings, community summaries,
  and cached LLM runs.
- DeepWiki-style wiki generation with catalog planning, detailed page generation,
  source citations, automatic diagrams, multi-language translation, and incremental
  updates.
- Pure frontend wiki exports: interactive standalone HTML and Obsidian vault ZIP.
- Design notes live in `docs/design.md`.

## Installation

Install the Python package from PyPI:

```bash
pip install codewiki
codewiki --help
```

Start CodeWiki after installation:

```bash
codewiki serve
```

Then open `http://127.0.0.1:8000` for the Web UI. The Python package includes the
built frontend; a source checkout is only needed for frontend development with Vite.

Configure local environment variables with:

```bash
codewiki config
codewiki config --set CODEWIKI_LLM__DEFAULT__MODEL=openai/gpt-4.1
codewiki config --profile qa --model openai/gpt-4.1 --api-key "$OPENAI_API_KEY"
codewiki config --list
```

## Wiki Workflow

1. Register and analyze a repository.
2. Build GraphRAG source chunks, optionally with embeddings.
3. Generate a wiki catalog.
4. Generate wiki pages from the catalog.
5. Use update/regenerate flows when code changes.

Wiki pages are generated from deterministic graph facts and retrieved source chunks.
The page prompt enforces a gather/think/write workflow and includes ReadFile evidence so
the model must stay close to real source files. Source references are validated before a
page is promoted to `generated`; otherwise the page is saved as `draft` with validation
errors.

Mermaid diagrams are generated server-side from validated graph facts. Invalid diagrams
are filtered out instead of failing the whole page, so a bad graph block should not turn
a good wiki page into a draft.

## Wiki Languages

The base wiki language is generated first. Other languages are produced by translating
the base catalog and pages while preserving slugs, source references, code identifiers,
links, and Markdown structure.

Set configured translation languages in `.env`:

```bash
CODEWIKI_WIKI_BASE_LANGUAGE=en
CODEWIKI_WIKI_TRANSLATION_LANGUAGES=zh
```

The frontend wiki page has an English/Chinese language switch above the left catalog
navigation. If a requested non-base language is missing, the backend generates the base
wiki first and then translates it.

## Wiki Export

The frontend wiki toolbar can export the currently selected language as:

- Interactive HTML: a standalone static page with catalog navigation, page switching,
  rendered Markdown, source sections, related pages, and Mermaid rendering.
- Obsidian vault: a ZIP containing Markdown pages, wiki links, source metadata, and
  minimal `.obsidian` settings.

Exports are built entirely in the browser from already-loaded wiki data and do not
require a backend export API.

## LLM Configuration

Run `codewiki config` or copy `.env.example` and fill in a default model profile:

```bash
cp .env.example .env
```

The default profile is used for every task unless a task-specific profile overrides it.
This is the simplest "use one model for everything" setup:

```bash
CODEWIKI_LLM__MODE=sdk
CODEWIKI_LLM__DEFAULT__MODEL=provider/strong-coding-model
CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE=
CODEWIKI_LLM__DEFAULT__ENDPOINT=
CODEWIKI_LLM__DEFAULT__API_KEY=
# Optional global output limit. Leave unset to use task defaults; 0 omits max_tokens.
# CODEWIKI_LLM__DEFAULT__MAX_TOKENS=0
CODEWIKI_LLM__TIMEOUT_SECONDS=120
CODEWIKI_LLM__MAX_RETRIES=3
CODEWIKI_LLM__CACHE_ENABLED=true
```

Each LLM task can override model, provider type, endpoint, API key, and max output tokens:

```bash
# Fast/cheap catalog planning. Raise this for large DeepWiki catalogs.
CODEWIKI_LLM__PROFILES__CATALOG__MODEL=
CODEWIKI_LLM__PROFILES__CATALOG__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__CATALOG__ENDPOINT=
CODEWIKI_LLM__PROFILES__CATALOG__API_KEY=
CODEWIKI_LLM__PROFILES__CATALOG__MAX_TOKENS=12000

# Strong source-grounded wiki page generation
CODEWIKI_LLM__PROFILES__PAGE__MODEL=
CODEWIKI_LLM__PROFILES__PAGE__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__PAGE__ENDPOINT=
CODEWIKI_LLM__PROFILES__PAGE__API_KEY=
CODEWIKI_LLM__PROFILES__PAGE__MAX_TOKENS=12000

# Translation
CODEWIKI_LLM__PROFILES__TRANSLATION__MODEL=
CODEWIKI_LLM__PROFILES__TRANSLATION__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__TRANSLATION__ENDPOINT=
CODEWIKI_LLM__PROFILES__TRANSLATION__API_KEY=
CODEWIKI_LLM__PROFILES__TRANSLATION__MAX_TOKENS=12000

# Ask / QA
CODEWIKI_LLM__PROFILES__QA__MODEL=
CODEWIKI_LLM__PROFILES__QA__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__QA__ENDPOINT=
CODEWIKI_LLM__PROFILES__QA__API_KEY=
# Set 0 to avoid forcing max_tokens on streaming QA.
CODEWIKI_LLM__PROFILES__QA__MAX_TOKENS=0

# Embeddings, used when GraphRAG vector indexing is enabled
CODEWIKI_LLM__PROFILES__EMBEDDING__MODEL=
CODEWIKI_LLM__PROFILES__EMBEDDING__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__EMBEDDING__ENDPOINT=
CODEWIKI_LLM__PROFILES__EMBEDDING__API_KEY=
```

Provider examples depend on LiteLLM. For OpenAI-compatible endpoints, set an endpoint
and API key. For native LiteLLM providers, set `PROVIDER_TYPE` and model according to
LiteLLM's provider naming.

Failed LLM provider calls are recorded in `llm_run` with `status=error`; API responses
return a `run_id` where possible so failures can be traced without exposing API keys.

## Development

```bash
# Install backend and frontend dependencies
make install

# Start FastAPI and Vite
make start

# Stop local dev servers on the configured ports
make kill
```

Default local URLs:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

Useful checks:

```bash
make lint
make test
make build
```

## CLI

```bash
# Register or inspect repositories
codewiki repos add . --name my-repo
codewiki repos list
codewiki repos scan .

# Full analysis and GraphRAG
codewiki analyze .
codewiki graphrag build .
codewiki graphrag build . --embeddings

# Symbol and graph intelligence
codewiki graph search "AuthService"
codewiki graph callers generate_page
codewiki graph impact GraphRAGRetriever
codewiki graph explore "wiki page generation"
git diff --name-only | codewiki graph affected --stdin

# Wiki generation
codewiki wiki catalog .
codewiki wiki pages .
codewiki wiki update . --language en
codewiki wiki page overview .

# Incremental graph update, with wiki regeneration enabled by default
codewiki update .
codewiki watch .

# GraphRAG grounded Q&A
codewiki ask "How does the main workflow fit together?"
codewiki ask --repo my-repo "Where are wiki pages generated?"

# MCP server for local AI assistants
codewiki mcp
# or: codewiki-mcp
```

Most commands accept a repository id, id prefix, registered name, path, or Git URL.
Use `--json` on CLI commands when machine-readable output is useful.

## MCP Server

CodeWiki can run as a local stdio MCP server so AI assistants can use the analyzed
repository graph and wiki as tools:

```json
{
  "mcpServers": {
    "codewiki": {
      "command": "codewiki",
      "args": ["mcp"],
      "env": {
        "CODEWIKI_DATABASE_URL": "sqlite+aiosqlite:///./data/codewiki.sqlite3"
      }
    }
  }
}
```

The MCP server exposes tools for repository registration/listing, AST analysis,
GraphRAG index building and retrieval, LLM-backed Q&A, graph search/exploration,
affected-file analysis, and generated wiki page reads.

## HTTP API Highlights

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/repos/{repo_id}/wiki/catalog?language=en` | Generate a wiki catalog |
| `POST` | `/api/repos/{repo_id}/wiki/pages/generate?language=en` | Generate all wiki pages |
| `POST` | `/api/repos/{repo_id}/wiki/pages/update?language=en` | Incrementally update stale/missing pages |
| `POST` | `/api/repos/{repo_id}/wiki/pages/{slug}/regenerate?language=en` | Regenerate one page |
| `POST` | `/api/repos/{repo_id}/wiki/translate` | Translate catalog and pages |
| `GET` | `/api/repos/{repo_id}/wiki?language=en` | Read the wiki catalog and pages |
| `POST` | `/api/repos/{repo_id}/ask` | Ask a GraphRAG-grounded question |
| `GET` | `/api/repos/{repo_id}/graph/search?q=...` | Search indexed symbols |
| `GET` | `/api/repos/{repo_id}/graph/callers?symbol=...` | Find callers/references |
| `GET` | `/api/repos/{repo_id}/graph/callees?symbol=...` | Find callees/references |
| `GET` | `/api/repos/{repo_id}/graph/impact?symbol=...` | Analyze change impact |
| `POST` | `/api/repos/{repo_id}/graph/explore` | Build grouped source exploration context |
| `POST` | `/api/repos/{repo_id}/graph/affected` | Find affected files/tests/wiki pages |

## Supported AST Languages

| Language | Parser | Extracted facts |
|---|---|---|
| Python | tree-sitter capture parser | imports, classes, functions, methods, decorators, calls, references, FastAPI-style endpoints |
| TypeScript / TSX | tree-sitter capture parser | imports/exports, classes, interfaces, type aliases, functions, methods, calls, route endpoints |
| JavaScript / JSX | tree-sitter capture parser | imports/exports, classes, functions, methods, calls, route endpoints |
| Java | tree-sitter capture parser | package/imports, classes, interfaces, records, enums, methods, constructors, inheritance, implementations, Spring-style endpoints |
| Go | tree-sitter capture parser | package/imports, structs, interfaces, type aliases, functions, receiver methods, calls, router-style endpoints |
| Rust | tree-sitter capture parser | imports, structs, enums, traits, impls, functions, methods, calls |
| C | tree-sitter capture parser | includes, structs, functions, calls |
| C++ | tree-sitter capture parser | includes, classes, structs, functions, methods, inheritance, calls |
| C# | tree-sitter capture parser | usings, namespaces, classes, interfaces, methods, inheritance, calls |

## Notes

The core contract is that code facts come from deterministic scanners and AST parsers
first. GraphRAG and LLM workflows consume those facts for retrieval, synthesis, and wiki
generation rather than inventing structure.
