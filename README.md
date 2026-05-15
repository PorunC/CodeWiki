# Code Wiki Platform

Single-user Code Wiki platform for AST-based code graph analysis, GraphRAG retrieval, and LiteLLM-powered wiki generation.

## Current Scope

- FastAPI backend with repository management, analysis runs, GraphRAG, wiki, ask, graph, file, and settings APIs.
- React/Vite frontend with repository management plus graph, wiki, ask, and settings pages.
- AST-based code graph extraction for Python, TypeScript, JavaScript, Java, and Go.
- Deterministic graph edges for imports, definitions, inheritance, implementations, calls, route handlers, source refs, and config usage.
- GraphRAG retrieval, LiteLLM routing, cached LLM runs, wiki catalog/page generation, and incremental update planning.
- Design notes live in `docs/design.md`.

## Supported AST Languages

| Language | Parser | Extracted facts |
|---|---|---|
| Python | stdlib `ast` | imports, classes, functions, methods, decorators, calls, references, FastAPI-style endpoints |
| TypeScript / TSX | tree-sitter | imports/exports, classes, interfaces, type aliases, functions, methods, calls, route endpoints |
| JavaScript / JSX | tree-sitter | imports/exports, classes, functions, methods, calls, route endpoints |
| Java | tree-sitter | package/imports, classes, interfaces, records, enums, methods, constructors, inheritance, implementations, Spring-style endpoints |
| Go | tree-sitter | package/imports, structs, interfaces, type aliases, functions, receiver methods, calls, router-style endpoints |

## Development

```bash
# install backend and frontend dependencies
make install

# start FastAPI and Vite
make start

# stop local dev servers on the configured ports
make kill

# CLI
codewiki analyze .
codewiki graphrag build
codewiki ask "How does the main workflow fit together?"

# Optional: give a repo a friendly name for later
codewiki repos add . --name my-repo
codewiki update my-repo

# Optional LLM routing
export CODEWIKI_LLM_SMALL_MODEL=provider/small-coding-model
export CODEWIKI_LLM_LARGE_MODEL=provider/strong-coding-model
export CODEWIKI_LLM_CATALOG_MODEL=provider/fast-catalog-model
export CODEWIKI_LLM_PAGE_MODEL=provider/strong-page-model
export CODEWIKI_LLM_QA_MODEL=provider/strong-qa-model
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

## Notes

The core contract is that code facts come from deterministic scanners and AST parsers first. GraphRAG and LLM workflows consume those facts for retrieval, synthesis, and wiki generation rather than inventing structure.
