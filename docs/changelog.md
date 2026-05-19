# Changelog

## [Unreleased]

## [0.2.0] - 2026-05-19

### Added

- **Packaged Web UI** — the Python package now bundles the built frontend, and
  `codewiki serve` can serve the Web UI without requiring a Vite development server.
- **Configuration CLI** — `codewiki config` can create, inspect, and update CodeWiki
  environment settings and LLM profiles from the command line.
- **MCP server** — `codewiki mcp` and `codewiki-mcp` start a stdio MCP server for
  local AI assistants, exposing tools for repository registration/listing, AST analysis,
  GraphRAG index building and retrieval, LLM Q&A, graph search/exploration,
  affected-file analysis, and generated wiki page reads.
- **Graph node search** — `code_node_fts` indexes graph node names, paths, languages,
  symbol ids, summaries, signatures, and docstrings for symbol-level search.
- **Graph query API** — endpoints now support symbol search, callers, callees, impact
  analysis, exploration context, affected-file analysis, and graph status.
- **Graph CLI** — `codewiki graph` adds `search`, `callers`, `callees`, `impact`,
  `explore`, `affected`, and `status` commands.
- **Incremental watcher** — `codewiki watch` runs polling-based incremental graph and
  source-chunk refreshes with debounce.
- **Chinese documentation** — the Simplified Chinese README is now maintained under
  `docs/README.zh-CN.md`.

### Changed

- **GraphRAG symbol seeding** — retrieval now uses node-level FTS before falling back to
  in-memory symbol matching.
- **Wiki prompt payloads** — page and catalog generation now use lightweight graph facts,
  omit duplicate chunk bodies, and avoid sending Mermaid edge payloads to the LLM.
- **Source chunk indexing** — file graph nodes remain in the graph but no longer produce
  full-file source chunks, reducing retrieval context size.
- **Documentation links** — README language links now point to the Chinese README in
  `docs/`.

### Fixed

- **Prompt budget control** — oversized lockfiles and single reads are skipped before they
  can dominate GraphRAG context or ReadFile evidence.
- **Repository scanning** — lockfiles are ignored during analysis so dependency snapshots
  do not enter source chunk indexes.
- **Wiki generation UX** — generation status refreshes no longer flash the whole wiki
  page while background polling is active.
- **Wiki generation reliability** — catalog prompts are smaller and avoid full graph
  metadata, reducing malformed JSON responses from long catalog generations.

## [0.1.0] - 2026-05-18

### Added

- **Python package release** — prepared the initial `codewiki` package release with a
  console entry point and PyPI publish workflow.
- **FastAPI backend** — repository management, analysis runs, graph, GraphRAG, wiki,
  ask, file, run, and settings APIs.
- **React/Vite frontend** — local development UI for repository management, graph
  exploration, wiki reading, Q&A, and settings.
- **Repository scanner** — local repository scanning with ignore handling, metadata
  persistence, and Git URL import support.
- **AST code graph** — deterministic extraction for Python, TypeScript/TSX,
  JavaScript/JSX, Java, Go, Rust, C, C++, and C#.
- **Graph facts** — imports, exports, definitions, inheritance, implementations, calls,
  route handlers, source references, configuration usage, and confidence/provenance
  metadata.
- **Graph explorer** — React Flow graph views with filters, breadcrumbs, detail panels,
  community drilldown, file-level views, and source-reference navigation.
- **Graph communities** — Leiden-based community detection with optional LLM-generated
  community summaries.
- **GraphRAG retrieval** — source chunk indexing, FTS search, optional sqlite-vec
  embeddings, hybrid ranking, graph expansion, and retrieval context building.
- **Grounded Q&A** — LiteLLM-backed answers using GraphRAG context and source citations.
- **Wiki generation** — DeepWiki-style catalog planning, grounded page generation,
  ReadFile evidence, source-reference validation, Mermaid diagrams, parent-page
  synthesis, and stale-page regeneration.
- **Wiki languages** — base-language generation plus translation workflows that preserve
  slugs, links, source references, code identifiers, and Markdown structure.
- **Wiki exports** — browser-side export to standalone interactive HTML and Obsidian
  vault ZIP archives.
- **Incremental updates** — AST cache, Git-diff detection, symbol recovery, source-chunk
  refreshes, and wiki regeneration for stale pages.
- **LLM operations** — LiteLLM task profiles, model routing, run recording, cache hits,
  prompt versioning, and provider failure tracing.
- **CLI workflows** — `repos`, `analyze`, `update`, `graphrag build`, `wiki`, `ask`,
  and `serve` commands with JSON output where useful.
- **Developer tooling** — Make targets for install, development servers, tests, linting,
  frontend builds, and port cleanup.
- **Architecture documentation** — design notes and repository guidelines for the
  backend, frontend, GraphRAG, wiki, and development workflow.

### Changed

- **Backend architecture** — services, persistence repositories, prompts, GraphRAG, wiki,
  and incremental update logic were split into focused modules.
- **AST parser architecture** — parser capture specs, capture engine, symbol topology,
  and language-specific augmenters were separated for maintainability.
- **Persistence layer** — graph, repository, GraphRAG, wiki, embedding, community, and
  LLM run storage moved to SQLAlchemy-backed repository modules.

### Fixed

- **Wiki generation** — invalid Mermaid diagrams are filtered without failing the whole
  page, and LLM provider failures are recorded without exposing secrets.
- **Graph explorer** — focus interactions, community drilldown behavior, and file detail
  graph layout were stabilized.
- **Source navigation** — wiki source references and graph navigation events were repaired
  so citations can link back to relevant files and graph nodes.
- **Development commands** — Make targets and local port cleanup were hardened for
  cross-platform development.
