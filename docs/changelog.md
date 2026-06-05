# Changelog

## [Unreleased]

### Changed

- **Legacy Python backend removal** — removed the old Python/FastAPI backend source,
  backend.app-dependent pytest suite, Python backend dependency lockfile, and stale
  development references. The TypeScript backend in `backend` is now the only
  active backend implementation.

## [0.6.4] - 2026-06-03

### Changed

- **DeepSeek prompt caching** — optimized wiki generation prompts and LLM cache
  usage for better provider-side cache locality.
- **GraphRAG evidence filtering** — filtered unresolved external placeholders,
  tests, generated output, and vendor files from default GraphRAG and Wiki evidence.
- **Documentation cleanup** — removed outdated standalone design notes and consolidated
  current architecture, PostgreSQL, community, and LLM cache details into the main
  README, usage guide, and design notes.

### Fixed

- **Wiki Mermaid repair** — repaired conjoined Mermaid fence headings and unwrapped
  fenced diagram placeholders so generated diagrams render more reliably.

## [0.6.3] - 2026-05-30

### Added

- **Frontend theme toggle** — added persisted light/dark mode switching across the
  application, including light-mode graph canvas, nodes, Mermaid diagrams, wiki,
  ask, repository, and settings surfaces.
- **Staged full analysis** — added staged full-analysis execution for repository
  analysis workflows.

### Changed

- **Wiki prompt cache locality** — split stable page-generation instructions from
  dynamic page payloads and warm up the first leaf page before concurrent generation
  to improve provider token-cache reuse.
- **README badges** — refreshed the project README header with documentation links,
  CI, license, PyPI download, and GitHub star badges.
- **Repository file scanning** — switched repository file scans to a lighter-weight
  path for lower overhead.

### Fixed

- **Backend typing** — fixed backend type-checking issues found by mypy.
- **Frontend graph loading** — avoided unnecessary background graph loads.
- **Translated wiki performance** — sped up translated wiki generation.

## [0.6.2] - 2026-05-27

### Fixed

- **Port cleanup on Linux** — `scripts/kill_ports.py` now falls back from process-group
  signaling to PID signaling when the process group cannot be signaled, while still
  ignoring already-exited listeners.

## [0.6.1] - 2026-05-27

### Added

- **Lite agent setup** — added `codewiki lite agents install`, `uninstall`, and
  `print-config` for wiring CodeWiki Lite MCP into Claude Code and Codex CLI.
- **Claude Code support** — local installs now write `.mcp.json`, `.claude/CLAUDE.md`,
  and optional MCP allow-list permissions for CodeWiki Lite tools.
- **Codex CLI support** — global installs now write `~/.codex/config.toml` and
  `~/.codex/AGENTS.md` entries for the `codewiki-lite` MCP server.
- **Lite Mode help** — top-level CLI help now includes a quick Lite Mode workflow.

### Changed

- **Lite agent internals** — split agent setup into focused target, registry, template,
  MCP config, type, and file I/O modules.
- **Lite docs** — documented Codex and Claude Code agent setup in the README and usage
  guides.

## [0.6.0] - 2026-05-27

### Added

- **Lite Mode** — added project-local `.codewiki/codewiki-lite.sqlite3` indexes for
  lightweight agent workflows without registering repositories in the main CodeWiki
  database.
- **Lite CLI** — added `codewiki lite init`, `index`, `sync`, `watch`, `status`,
  `query`, `context`, `trace`, `node`, `files`, `callers`, `callees`, `impact`, and
  `affected` commands.
- **Lite MCP support** — added `codewiki mcp --lite --path ...` plus agent-facing
  context, trace, node, and graph tools backed by the Lite index.
- **Lite Mode benchmarking** — added a synthetic stress runner and documented
  600-module and 2,000-module Lite Mode benchmark results.

### Changed

- **Indexed file reads** — `codewiki lite files` now reads indexed file nodes by
  default, with `--live` available for filesystem scans.
- **Service organization** — grouped community services under
  `backend.app.services.community`, grouped LLM services under
  `backend.app.services.llm`, and split affected-file helpers from graph query logic.
- **Root npm wrapper** — removed the redundant root `package.json`; frontend package
  metadata remains under `frontend/`.

### Fixed

- **Lite sync freshness** — Lite and MCP context responses now report pending sync
  status and pending files when graph context is stale.
- **Incremental containment recovery** — preserved file-to-symbol `contains` edges
  during incremental sync so reused files keep stable graph containment.
- **Repository scanning** — ignored `.codewiki/` Lite Mode state during source scans.

## [0.5.1] - 2026-05-26

### Added

- **Deeper wiki generation controls** — exposed GraphRAG retrieval depth and source
  budget settings through environment configuration so generated wiki pages can use
  broader repository context when needed.
- **Python type checking workflow** — added mypy as a development dependency, a
  `make typecheck` target, typing guidance in the project docs, and backend typecheck
  coverage in GitHub Actions.

### Changed

- **Wiki page analysis depth** — strengthened page generation prompts to produce more
  detailed subsystem explanations, implementation reasoning, workflows, data contracts,
  operational notes, and source-grounded trade-offs.
- **Backend typing coverage** — cleaned up typing across wiki generation, GraphRAG
  context packing, graph building, repository mixins, CLI/MCP helpers, and LLM gateway
  boundaries so backend mypy checks run without broad error-code suppression.

### Fixed

- **Wiki citation rendering** — normalized malformed source markers, removed unresolved
  `[[S??]]` placeholders, and prevented adjacent source labels from collapsing into
  ambiguous single-link text.
- **Wiki diagram output** — removed generated diagram explanation blocks from rendered
  pages while preserving validated Mermaid diagrams and source references.

## [0.5.0] - 2026-05-23

### Added

- **PostgreSQL storage backend** — added `postgresql+psycopg://...` store dispatch,
  schema creation, SQLAlchemy dialect helpers, PostgreSQL-safe schema patches, and
  integration coverage for repo, graph, wiki, LLM run, delete, and incremental update
  workflows.
- **PostgreSQL native retrieval** — added `websearch_to_tsquery`/`to_tsvector` search
  paths with GIN indexes for graph node and source chunk search.
- **pgvector search** — added PostgreSQL vector tables, embedding insert/list/search,
  HNSW cosine indexes, pgvector schema qualification, and delete cleanup support.
- **PostgreSQL deployment support** — added Docker runtime dependencies, Compose
  PostgreSQL service examples, `.env` PostgreSQL URL examples, and package metadata for
  PostgreSQL/pgvector.
- **CI test workflow** — added a GitHub Actions test workflow for backend lint/tests,
  PostgreSQL integration tests, frontend lint/build, and package build checks.

### Changed

- **Store abstraction** — moved application-facing persistence annotations to
  `CodeWikiStore` while preserving SQLite as the default local backend.
- **Batching and compatibility** — made write batch sizing backend-aware and guarded
  SQLite-only FTS/vector SQL behind backend capability checks.
- **Documentation** — updated README and design notes with PostgreSQL, pgvector,
  database configuration, and fallback behavior.

### Fixed

- **PostgreSQL defaults** — made timestamp/text defaults and URL password handling safe
  for PostgreSQL schema creation and smoke tests.
- **PostgreSQL vector search** — qualified pgvector types, operators, and opclasses so
  installations outside the active search path continue to work.

## [0.4.0] - 2026-05-22

### Added

- **Layered repository benchmark runner** — added `scripts/benchmark_repos.py` for
  repeatable cold repository pressure tests with JSONL/CSV output, progress reporting,
  timeout handling, and repository manifests.
- **Cold benchmark report** — documented React and VS Code cold analyze pressure-test
  results, database write scale, throughput estimates, and SQLite persistence findings.
- **Docker deployment support** — added Docker and Compose files for packaged local
  deployment.
- **MIT license** — added the project license file.

### Changed

- **Analyze throughput** — reused file scan hashes, cached source file reads, and
  parallelized parsing to reduce repeated analysis cost.
- **GraphRAG indexing** — chunk and embedding indexes now sync incrementally instead of
  rebuilding unchanged records.
- **SQLite persistence** — large graph, chunk, community, and embedding writes are now
  committed in 500-row batches with ignore/upsert semantics to avoid long-running giant
  transactions during large cold analyzes.
- **Benchmark observability** — long-running benchmark heartbeats now include SQLite row
  counts for key tables so persistence progress is visible while the command is running.
- **LLM routing** — task output token limits can now be configured per profile with
  `CODEWIKI_LLM__PROFILES__<TASK>__MAX_TOKENS`.

### Fixed

- **Code node FTS backfill** — skipped redundant FTS rebuilds when graph node search rows
  are already in sync.
- **Large benchmark writes** — reduced oversized WAL buildup and made intermediate
  database writes visible during pressure tests.

## [0.3.0] - 2026-05-21

### Added

- **Hierarchical communities** — graph analysis now builds multi-level communities and
  derived community edges so large repositories can be explored at progressively finer
  levels.
- **Community hierarchy prompts** — GraphRAG and wiki prompts include community hierarchy
  relationships to improve context for architecture-level explanations.
- **Hierarchical graph views** — the frontend can render and navigate community levels
  in graph views.
- **Collapsible wiki catalog sections** — wiki catalog navigation supports collapsing
  sections for easier browsing of larger generated documentation sets.

### Changed

- **Community navigation** — community level navigation moved into breadcrumbs, making
  drilldown paths clearer in the graph UI.
- **Analysis progress** — graph analysis progress reporting was expanded so long-running
  operations expose more useful status.
- **LLM routing** — maximum output tokens can be configured per LLM task profile.
- **Wiki catalog scaling** — catalog generation was made more resilient for larger
  repositories and translation workflows.

### Fixed

- **Community drilldown routing** — parent community drilldown now redirects correctly
  and hierarchical drilldown interactions are more stable.
- **Wiki translation resilience** — translation flows handle larger catalog structures
  more reliably.

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
