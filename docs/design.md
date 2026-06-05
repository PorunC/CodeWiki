# Code Wiki Platform Design

> Legacy note: this document describes the earlier Python/FastAPI backend design.
> The current default backend is the TypeScript/Fastify npm package in
> `backend-ts`; see `docs/typescript-backend.md` for the active architecture,
> package boundaries, CI, and npm publishing flow.

## 1. 目标定位

Code Wiki Platform 是一个单用户、本地优先的代码理解平台。它把一个本地目录或
Git URL 转换为可检索、可视化、可生成文档的代码知识库：

1. 扫描仓库，识别源码、配置、忽略规则和 Git 元数据。
2. 用 AST 和 tree-sitter 提取文件、符号、调用、继承、导入、路由等确定性事实。
3. 构建 Code Graph，并在图上做社区检测。
4. 构建 GraphRAG source chunks、FTS 检索和可选向量索引。
5. 基于 GraphRAG 生成 source-grounded Wiki 和问答结果。
6. 在前端提供 Graph、Wiki、Ask、Settings 一体化工作台。

项目重点不是团队协作或 SaaS，而是让开发者快速理解陌生仓库，并且能追溯每个
文档结论背后的源码。

## 2. 当前实现概览

```text
Repo path / Git URL
  -> RepoScanner
       FileSystemWalker + IgnoreMatcher + GitOperations + LanguageDetector
  -> AnalysisPipeline
       AstParser -> GraphBuilder -> CommunityDetector -> CommunityRecordBuilder
  -> CodeWikiStore
       graph tables, communities, chunks, wiki, llm runs
  -> GraphRAGRetriever
       symbol seeds + FTS chunks + optional vectors + graph expansion + communities
  -> LLM workflows
       CommunityNamer, WikiGenerator, QuestionAnswerer
  -> FastAPI
       repos, runs, graph, files, wiki, ask, settings
  -> React frontend
       graph explorer, wiki reader/exporter, ask panel, repo/settings UI
```

核心原则：

- AST 和扫描器提供事实，LLM 只负责组织和解释。
- 所有 Wiki 页面必须通过源码引用校验后才能成为 `generated`。
- 图谱、检索、文档生成、翻译、导出各自有清晰边界。
- LLM 调用必须可缓存、可追踪、可失败降级。

## 3. 参考项目取舍

| 参考项目 | 借鉴点 | 当前落地 |
|---|---|---|
| CodeWiki | 自底向上页面生成、模块树、Agent 工具读取源码 | 目前采用叶子页先生成、父页汇总子页，并加入 ReadFile evidence；尚未引入完整递归 Agent runtime |
| OpenDeepWiki | Catalog/Page 两阶段、源码约束 prompt、多语言翻译、Mermaid 穿插 | 已实现 catalog/page/translation、强制 gather/think/write prompt、服务端图表生成和容错 |
| GitNexus | 图管线、edge confidence、Leiden 社区检测 | 已实现加权社区检测、deterministic/inferred 边和 provenance metadata |
| Understand-Anything | 图谱 overview/detail、布局和 drilldown | 前端已实现 overview/file/focus/drilldown 多视图和图筛选 |
| graphify | 轻量 AST 抽取、缓存和社区辅助 | 已实现 AST cache、source chunk、FTS/embedding 可选检索 |

## 4. 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12, FastAPI, SQLAlchemy |
| 数据库 | SQLite + FTS5 + sqlite-vec, PostgreSQL + tsvector/GIN + optional pgvector |
| AST | tree-sitter grammars, capture specs, language augmenters |
| 图计算 | NetworkX, graspologic Leiden fallback to NetworkX Louvain/greedy |
| LLM | LiteLLM SDK, task profile routing, cached LLM runs |
| CLI | Click |
| 前端 | React 19, TypeScript, Vite |
| 图 UI | @xyflow/react, ELK.js |
| Wiki UI | react-markdown, remark-gfm, mermaid |
| 导出 | Pure frontend HTML builder and stored ZIP writer |

## 5. 后端模块边界

### 5.1 API 层

`backend/app/api` 负责 HTTP 适配，不承载核心业务逻辑：

| 文件 | 职责 |
|---|---|
| `repos.py` | 注册、列出、删除仓库 |
| `runs.py` | full analysis、incremental update、analysis run 查询 |
| `graph.py` | graph/communities/GraphRAG build/retrieve |
| `wiki.py` | catalog/page/update/regenerate/translate/read |
| `ask.py` | GraphRAG-grounded Q&A |
| `files.py` | 源文件读取 |
| `settings.py` | LLM routing 配置展示 |
| `dependencies.py` | 简单服务容器，缓存 Store、LLMGateway、GraphRAGRetriever、WikiGenerator |

API 层会把 `ValueError` 映射为 400/404，把 LLM provider 失败映射为 502，并尽量返回
`run_id` 便于排查。

### 5.2 Repository Scanner

`backend/app/services/repo_scanner` 已拆成可测试组件：

| 组件 | 职责 |
|---|---|
| `RepoScanner` | 识别本地目录或 Git URL，组装扫描结果 |
| `FileSystemWalker` | 遍历文件系统，处理目录剪枝、大小限制、二进制跳过 |
| `IgnoreMatcher` | 解析 `.gitignore` 和默认忽略规则 |
| `GitOperations` | clone、commit hash、文件最近提交时间 |
| `LanguageDetector` | 扩展名/文件名到语言类型 |
| `scan_file` | 文件 hash、行数、语言、source 标记 |

扫描结果不直接构图，而是产出 `RepoScanResult`，由 `AnalysisPipeline` 后续消费。

### 5.3 AST Parser

AST 层的核心 contract 是 `AstSymbol`：

```python
AstSymbol(
    id="backend/app/api/wiki.py::generate_pages",
    type="function",
    name="generate_pages",
    file_path="backend/app/api/wiki.py",
    language="python",
    start_line=...,
    end_line=...,
    parent_id=None,
    signature="...",
    imports=[...],
    calls=[...],
    references=[...],
    bases=[...],
    implements=[...],
    metadata={...},
)
```

实现结构：

- `ast_parsers/capture_specs/*` 定义语言 capture query。
- `ast_parsers/capture_engine/*` 把 capture 结果标准化为符号。
- `ast_parsers/augmenters/*` 做语言特定增强，例如 exports、endpoint、schema、receiver method。
- `AstParserRegistry.default()` 注册 Python、Java、Go、Rust、C、C++、C#、TS/TSX、JS/JSX。
- `AstCache` 按内容 hash 缓存解析结果，减少重复解析成本。

### 5.4 Analysis Pipeline

`AnalysisPipeline` 是 full analysis 和 incremental update 的共享核心：

```text
RepoScanResult
  -> parse_scanned_files
  -> GraphBuilder.build
  -> CommunityDetector.detect
  -> CommunityRecordBuilder.build_all
  -> CodeWikiStore.replace_graph / replace_graph_communities
```

职责拆分：

| 组件 | 职责 |
|---|---|
| `AnalysisService` | full analysis orchestration、analysis_run 状态、社区 LLM 命名调度 |
| `IncrementalUpdater` | 变更计划、复用旧符号、局部 chunk 刷新、标记 stale pages |
| `AnalysisPipeline` | 共享扫描、解析、构图、社区检测管线 |
| `CommunityDetector` | 只做图分区，不负责命名和摘要生成 |
| `CommunityRecordBuilder` | 从 partitions + graph facts 生成 deterministic community records |
| `CommunityNamer` | 可选 LLM 命名和摘要增强 |

## 6. Code Graph 设计

### 6.1 节点类型

| 类型 | 来源 | 说明 |
|---|---|---|
| `repository` | scanner | 仓库根节点 |
| `directory` | scanner/graph builder | 目录层级 |
| `file` | scanner | 源文件 |
| `config` | config detector | 配置文件或配置节点 |
| `module` | import resolver | 外部模块或无法解析的模块 |
| `class` | AST | 类 |
| `interface` | AST | 接口、trait、protocol |
| `schema` | AST/augmenter | 数据类型、DTO、type alias |
| `function` | AST | 函数 |
| `method` | AST | 类方法、receiver method |
| `endpoint` | AST/augmenter | HTTP route 或框架入口 |

### 6.2 边类型

| 类型 | 说明 | 常见置信度 |
|---|---|---|
| `contains` | repository/directory/file/class 包含下级节点 | deterministic |
| `defines` | file 定义符号 | deterministic |
| `imports` | file 导入 file/module | deterministic 或解析后 inferred |
| `exports` | file 导出符号 | deterministic |
| `calls` | 函数/方法调用目标符号 | inferred for cross-file resolution |
| `references` | 符号引用目标符号 | inferred |
| `inherits` | class/schema 继承目标 | deterministic 或 name resolution inferred |
| `implements` | class 实现接口 | deterministic 或 name resolution inferred |
| `routes_to` | endpoint 指向 handler | framework-detected inferred |
| `uses_config` | file/symbol 使用配置文件 | inferred |

### 6.3 GraphBuilder 阶段

`GraphBuilder.build()` 已拆成阶段方法：

1. `_build_file_nodes`
   - 创建 repository、directory、file/config 节点。
   - 添加 directory/file containment edges。
2. `_build_symbol_nodes`
   - 把 `AstSymbol` 变成 graph symbol node。
3. `_build_file_import_edges`
   - import resolver 解析本地文件、外部模块、配置引用。
4. `_build_symbol_structure_edges`
   - 添加 contains/defines/exports/inherits/implements/routes_to。
5. `_build_call_reference_edges`
   - 添加 calls/references/uses_config。

每条边通过 `with_edge_provenance` 写入 reason、confidence level、inferred 标记，前端可用这些
metadata 做筛选和可视化表达。

## 7. 社区检测和命名

社区检测分两步：

```text
CodeGraph nodes/edges
  -> CommunityDetector.detect
       weighted undirected graph
       graspologic Leiden -> networkx Louvain -> greedy fallback
  -> CommunityRecordBuilder.build_all
       deterministic name/summary from files, symbols, internal/boundary edges
  -> optional CommunityNamer
       LLM batch rename/summarize, record llm_run
```

设计取舍：

- Community 是图结构分区，不等同于 Wiki catalog module。
- Detector 不生成名称和摘要，避免算法和 presentation 耦合。
- LLM 命名失败不会影响 analysis 成功，最多返回 `partial` 或 `failed` naming result。

## 8. GraphRAG 设计

GraphRAG 是建立在 Code Graph 上的 retrieval layer，不替代 AST 事实。

### 8.1 Index build

`GraphRAGRetriever.build_index()`：

1. 从 graph nodes 构建 source chunks。
2. 写入 `code_chunk`。
3. 同步写入后端文本索引：SQLite 写入 `code_chunk_fts`，PostgreSQL 使用表达式 GIN 索引。
4. 可选调用 embedding profile 构建向量，并记录 `code_chunk_embedding` metadata。

### 8.2 Retrieval flow

```text
query
  -> seed_from_symbols(query, graph nodes)
  -> search_fts(SQLite FTS5 or PostgreSQL tsvector)
  -> optional search_vectors(sqlite-vec or pgvector + embedding profile)
  -> merge chunk hits into seed nodes
  -> fallback overview seeds if empty
  -> graph expansion, max_hops 0..4
  -> related_edges(selected nodes)
  -> select_source_chunks(token budget, proximity, FTS/vector hits)
  -> community_summaries(selected nodes)
  -> context_pack + trace_id
```

输出 `RetrievalTrace` 包含：

- seed nodes
- expanded nodes
- related edges
- source chunks
- community summaries
- structured context pack
- stable trace id

### 8.3 使用场景

| 使用方 | 用途 |
|---|---|
| Wiki catalog | repository overview context |
| Wiki page | page topic focused context |
| QuestionAnswerer | answer prompt context |
| Frontend graph | GraphRAG 返回节点可高亮到图谱 |

## 9. Wiki 生成设计

Wiki 子系统是当前最复杂的业务域，已拆分成 facade、orchestrator、generator、validator、
payload builder、translation support、diagram support 等组件。

### 9.1 组件职责

| 组件 | 职责 |
|---|---|
| `WikiGenerator` | Facade，只暴露 catalog/page/update/regenerate/translate 公共方法 |
| `WikiPageOrchestrator` | 页面树遍历、叶子并发、父页自底向上生成、update dirty plan |
| `WikiTranslationOrchestrator` | base language 回退、多语言生成、翻译增量调度 |
| `WikiCatalogGenerator` | catalog prompt payload、LLM 调用、catalog JSON 校验 |
| `WikiPageGenerator` | 单页 GraphRAG、ReadFile evidence、LLM 调用、校验、保存 |
| `PageGenerationPayloadBuilder` | 构造 page prompt payload |
| `PageResponseValidator` | JSON content、source refs、citation、diagram placeholder 校验 |
| `WikiTranslator` | catalog/page 翻译、repair retry、保留 slugs/source refs |
| `llm/messages.py` | 统一 LLM message builder，稳定 contract 和动态 payload 分离 |
| `WikiIncrementalStrategy` | missing/draft/stale/metadata dirty page detection |
| `wiki/tree.py` | catalog tree traversal、GenerationNode、child page lookup |
| `wiki/diagrams/*` | 从 graph facts 生成 Mermaid 图 |
| `wiki/sources/*` | citation、source url、source/source list rendering |

### 9.2 Catalog generation

Catalog 不是文件树直译，而是面向阅读的模块树：

```text
Repo context + module candidates + GraphRAG overview
  -> catalog.md prompt
  -> LLM JSON
  -> _validate_catalog_payload
  -> normalized DocCatalogRecord
```

Catalog payload 包含：

- repository metadata
- repository context
- module candidates
- source chunks
- community summaries
- granularity contract
- required special pages
- JSON shape contract

目标是拆出更细的 leaf pages，而不是一个粗粒度 Backend/Frontend 页面。

### 9.3 Page generation

单页生成流程：

```text
catalog item
  -> GraphRAG retrieve(topic, max_hops=3)
  -> add source_hints chunks
  -> compute allowed_source_refs
  -> ReadFile evidence from repo path
  -> diagram plan from graph facts
  -> PageGenerationPayloadBuilder.build
  -> page.md system prompt
  -> stable page generation contract message
  -> dynamic Page payload message
  -> LLM JSON response
  -> JSON repair retry if needed
  -> PageResponseValidator
       source_refs exist and are allowed
       citations match returned refs
       markdown has required sections
       diagram placeholders are known
  -> replace citations
  -> compose relevant source files + diagrams + source list
  -> validate Mermaid blocks
  -> upsert DocPageRecord
```

状态规则：

- `generated`: LLM JSON 和 markdown/source refs 校验通过。
- `draft`: LLM provider 调用失败、JSON 修复失败、source_refs 失败或 markdown 基础校验失败。
- Mermaid 图表失败不会直接导致 draft。系统会先保留可解析图表；仍失败则移除服务端图表并保留正文。

### 9.4 Source refs 和 citations

LLM 只能引用 `allowed_source_refs` 中的文件范围。服务端会：

- 校验文件存在、行号存在、范围合理。
- 自动补齐 markdown citation 使用到但 response 未显式列出的 source refs。
- 过滤未使用 source refs，避免页面底部过长。
- 将 `[[S1]]` 类 citation marker 替换为 source links。
- 前端将相关源文件和完整来源列表折叠显示，中文页面使用中文标签。

### 9.5 Diagrams

图表不由 LLM 直接写 Mermaid，而由服务端从 graph facts 生成。当前图表类型：

| kind | Mermaid | 目的 |
|---|---|---|
| `component` | `graph TD` | 组件/文件/社区关系 |
| `data_flow` | `flowchart LR` | 调用、路由、导入形成的数据或控制流 |
| `symbol_flow` | `flowchart TD` | endpoint/function/method/config 级实现流 |
| `sequence` | `sequenceDiagram` | 紧凑交互顺序 |
| `data_model` | `classDiagram` | class/schema/interface 关系 |
| `surface` | `flowchart TD` | API 或公开 surface 到所属组件 |

页面 prompt 会收到 diagram slots，LLM 可以在正文中穿插 `[[DIAGRAM:...]]` 占位符。
未使用的有效图会按 heading hint 自动插入到合适章节。

### 9.6 Translation

多语言策略：

- `wiki_base_language` 是事实生成语言。
- 非 base 语言请求会先确保 base catalog/pages 存在。
- Catalog 翻译只翻译人类可见标题，保留 slug/path/topic/source_hints。
- Page 翻译只翻译 prose/headings，保留代码块、路径、链接、source refs、graph refs。
- 中文翻译 prompt 要求更自然的中文技术文档表达，避免机器翻译腔。
- 配置语言生成后，base page update 只翻译 dirty slugs。
- Page 翻译同样使用稳定 translation contract + 动态 translation payload 的 message 形状；
  批量翻译页面时先翻译第一页预热 provider 前缀缓存，再按并发上限翻译后续页面。

### 9.7 Incremental Wiki Update

Wiki 增量有两层：

1. `IncrementalUpdater`
   - 根据 git diff + sha256 计算 changed/new/deleted/unchanged。
   - 复用 unchanged 文件的旧 symbols。
   - 刷新 changed/new 文件 chunks。
   - 根据 changed files、deleted files、affected graph refs 标记 doc pages stale。
2. `WikiIncrementalStrategy`
   - 对 catalog nodes 和 existing pages 做 dirty planning。
   - missing、draft、stale、metadata changed 页面需要重新生成。
   - translated language 页面如果缺失、draft 或 base slug 刚生成，需要重新翻译。

## 10. LLM 路由、缓存和异常

### 10.1 配置模型

配置使用 Pydantic nested settings，不兼容旧的扁平配置：

```text
CODEWIKI_LLM__DEFAULT__MODEL
CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE
CODEWIKI_LLM__DEFAULT__ENDPOINT
CODEWIKI_LLM__DEFAULT__API_KEY
CODEWIKI_LLM__DEFAULT__MAX_TOKENS
CODEWIKI_LLM__PROFILES__PAGE__MODEL
CODEWIKI_LLM__PROFILES__PAGE__MAX_TOKENS
CODEWIKI_LLM__PROFILES__TRANSLATION__MODEL
...
```

`ModelRouter` 负责 task type 到 profile：

| task_type | 默认策略 |
|---|---|
| `catalog` | default max_tokens 4096; override with `CODEWIKI_LLM__PROFILES__CATALOG__MAX_TOKENS` |
| `community_summary` | default max_tokens 4096; override with `CODEWIKI_LLM__PROFILES__COMMUNITY_SUMMARY__MAX_TOKENS` |
| `cluster` | aliases to community_summary unless `CODEWIKI_LLM__PROFILES__CLUSTER__*` is set |
| `page` | default max_tokens 12000; override with `CODEWIKI_LLM__PROFILES__PAGE__MAX_TOKENS` |
| `translation` | default max_tokens 12000; override with `CODEWIKI_LLM__PROFILES__TRANSLATION__MAX_TOKENS` |
| `qa` | streaming profile flag; optional `CODEWIKI_LLM__PROFILES__QA__MAX_TOKENS` |
| `embedding` | embedding profile |

每个 task 可独立配置 model、provider_type、endpoint、api_key、max_tokens；空值继承
default profile。`max_tokens=0` 表示不向 provider 传输出上限。

### 10.2 LLMOperation

业务代码不再手动散落 cache key，而是通过 `LLMOperation` 声明：

- `task_type`
- `messages`
- `input_payload`
- `cache_namespace`
- `cache_parts`
- `model_alias`
- `prompt_version`
- `response_format`

`CachedLLMService` 调用 `complete_with_cache`，统一完成缓存读取、成功记录、失败记录。

### 10.3 Message shape 和 provider prefix cache

LLM 请求同时优化两种缓存：

1. 本地 response cache：`complete_with_cache` 通过 `input_payload` 的稳定 hash 命中已成功的
   `llm_run`，命中后不再调用 provider。
2. Provider prefix cache：请求 message 采用稳定前缀形状，让 DeepSeek 等 OpenAI-compatible
   provider 更容易复用 `prompt_cache_hit_tokens`。

统一 message 形状由 `backend/app/services/llm/messages.py` 提供：

```text
system prompt
stable contract message    # instructions / output shape / validation contract
dynamic payload message    # repo/page/question/translation-specific data, always last
```

当前使用该形状的路径包括 catalog、page、translation、QA、community naming。Wiki page
generation 和 translation 是主要收益场景，因为它们会在同一批任务中复用大量相同规则，只替换最后
的页面或翻译 payload。

批量执行也配合 prefix cache：

- Wiki page generation 先生成第一个 leaf page，再并发生成后续 leaf pages。
- Wiki translation 先翻译第一个 page，再并发翻译后续 pages。
- Repair retry 把 validation errors / previous response 放进动态 payload，不改变稳定 contract 前缀。

### 10.4 llm_run

每次调用记录：

- task_type, provider, model, model_alias
- prompt_version, cache_key, input_hash
- tokens, usage, response_content
- cached/status/error

`response_usage` 会标准化 provider cache 指标：

- `prompt_cache_hit_tokens`
- `prompt_cache_miss_tokens`
- `prompt_cache_hit_ratio`

本地 cache 命中会继续记录新的 `llm_run(cached=True)` 审计行，但聚合 provider cache ratio 时不会
把这些本地命中重复计入 provider token 分母。

Provider 异常会被脱敏并记录为 `status=error`，再抛出 `LLMCallError`。Wiki page 生成捕获
page task 的 provider 错误并保存 draft，其他 API 通常返回 502 和 run_id。

### 10.5 Wiki cache observability

Wiki API 会返回 `llm_cache` 聚合摘要，用于页面生成、增量更新、翻译和 wiki 读取：

- `run_count`
- `local_cache_hits`
- `provider_measured_runs`
- `prompt_tokens`
- `prompt_cache_hit_tokens`
- `prompt_cache_miss_tokens`
- `prompt_cache_hit_ratio`

前端 Wiki 摘要栏展示 provider cache hit ratio；生成/更新完成提示也会显示本次 provider cache
命中情况。没有 provider cache usage 的模型会显示 `n/a`，不把本地 response cache 误报为 provider
prefix cache。

## 11. 数据模型

主要表：

| 表 | 说明 |
|---|---|
| `repo` | 仓库元数据、路径、Git URL、commit hash |
| `analysis_run` | full/incremental analysis 运行记录和统计 |
| `code_node` | graph node，含 JSON metadata/provenance |
| `code_edge` | graph edge，含 confidence/is_inferred/metadata |
| `graph_community` | 社区记录，含 node_ids、summary |
| `code_chunk` | GraphRAG source chunk |
| `code_chunk_fts` | SQLite FTS5 虚拟表，PostgreSQL 使用 `to_tsvector` 表达式和 GIN 索引 |
| `code_chunk_embedding` | chunk embedding metadata 和 vec row mapping |
| `doc_catalog` | language-aware wiki catalog |
| `doc_page` | language-aware wiki page |
| `llm_run` | LLM 缓存、审计和错误记录 |

关键约束：

- `doc_page` 唯一键是 `(repo_id, language_code, slug)`。
- `doc_catalog` 按 `(repo_id, language_code, generated_at)` 查询最新版本。
- `llm_run` 缓存键包含 repo、task_type、cache_key、input_hash、model、prompt_version。
- `code_chunk` 按 repo/content_hash/file/range 去重。

数据库后端：

- `CodeWikiStore` 是服务、API、CLI、MCP 共享的持久化门面，由 `create_store()` 根据
  `CODEWIKI_DATABASE_URL` 分派到 `SQLiteStore` 或 `PostgresStore`。
- SQLite 是默认本地模式，使用 FTS5 和 `sqlite-vec` 保存/检索 embedding 向量。
- PostgreSQL 使用 `postgresql+psycopg://...` URL，schema 由 SQLAlchemy 创建，历史轻量
  migrations 通过 inspector 和 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 补齐。
- PostgreSQL 文本检索使用 `websearch_to_tsquery`、`to_tsvector` 和 GIN 表达式索引，避免
  走 SQLite FTS5 SQL。
- PostgreSQL 启动时尝试 `CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public`，再读取
  pgvector 实际安装 schema。pgvector 可用时按维度创建
  `code_chunk_embedding_vec_<dimensions>` 表，并建立 repo/model 过滤索引和 HNSW cosine
  向量索引；不可用时只保留 embedding metadata，vector search 返回空结果并让 GraphRAG
  继续使用 symbol、FTS 和 graph expansion。

## 12. Frontend 设计

### 12.1 App shell

前端是单页工作台，主导航包括：

- Repos
- Graph
- Wiki
- Ask
- Settings

路由状态通过 URL path 和 selected repo 同步。

### 12.2 Graph page

Graph page 由 `useGraphPageController` 统一管理状态：

| 状态/功能 | 说明 |
|---|---|
| view mode | overview, file, focus, drilldown |
| filters | node types, edge types, inferred calls, isolated communities |
| layout | `useVisualGraph` + ELK |
| selection | selected raw node, visual node, file id |
| navigation events | Ask 高亮、Wiki source ref 跳转到图谱 |
| analysis actions | full analyze, incremental update |

Graph UI 包含 filters panel、files panel、canvas、breadcrumbs、toolbar、node details。

### 12.3 Wiki page

Wiki page 负责：

- repo selector
- language toggle: English/中文
- catalog tree
- page generation/update/regenerate
- resizable left catalog
- right-side current page outline
- source refs grouped/collapsible display
- related pages
- interactive HTML export
- Obsidian vault export

Wiki 左侧切换页面时会滚动回文章顶部。右侧 outline 根据当前页面 h2/h3 自动生成。

### 12.4 Ask page

Ask 调用 `/api/repos/{repo_id}/ask`：

- 发送 question、max_hops、include_sources、include_graph。
- 展示 answer、sources、related nodes/edges/communities。
- 通过 frontend navigation event 高亮 Graph 相关节点。

### 12.5 Export

Export 是纯前端实现：

- `buildInteractiveWikiHtml` 把已加载 wiki 数据序列化进单个 HTML 文件。
- HTML 内置搜索、catalog 切换、sources、related pages 和静态样式。
- `buildObsidianVaultArchive` 生成 ZIP，包含 `Home.md`、页面 Markdown、wiki links 和 `.obsidian/app.json`。
- 不依赖后端导出 API。

## 13. HTTP API

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/api/health` | 健康检查 |
| `GET/POST/DELETE` | `/api/repos` | 仓库管理 |
| `POST` | `/api/repos/{repo_id}/analyze` | full analysis |
| `POST` | `/api/repos/{repo_id}/update` | incremental update，可自动 regenerate wiki |
| `GET` | `/api/repos/{repo_id}/runs` | analysis runs |
| `GET` | `/api/repos/{repo_id}/graph` | graph nodes/edges/communities |
| `GET` | `/api/repos/{repo_id}/graph/nodes/{node_id}` | 节点摘要 |
| `GET` | `/api/repos/{repo_id}/communities` | 社区列表 |
| `POST` | `/api/repos/{repo_id}/communities/name` | LLM 社区命名 |
| `POST` | `/api/repos/{repo_id}/graphrag/build` | 构建 chunks/embeddings |
| `POST` | `/api/repos/{repo_id}/graphrag/retrieve` | 返回 RetrievalTrace |
| `POST` | `/api/repos/{repo_id}/wiki/catalog?language=en` | 生成 catalog |
| `POST` | `/api/repos/{repo_id}/wiki/pages/generate?language=en` | 生成全部页面 |
| `POST` | `/api/repos/{repo_id}/wiki/pages/update?language=en` | Wiki 增量更新 |
| `POST` | `/api/repos/{repo_id}/wiki/pages/{slug}/regenerate?language=en` | 单页重生成 |
| `POST` | `/api/repos/{repo_id}/wiki/translate` | 翻译 catalog/pages |
| `GET` | `/api/repos/{repo_id}/wiki?language=en` | 读取 wiki |
| `GET` | `/api/repos/{repo_id}/wiki/pages/{slug}?language=en` | 读取页面 |
| `POST` | `/api/repos/{repo_id}/ask` | GraphRAG Q&A |
| `GET` | `/api/settings/llm/models` | 当前 LLM routing profiles |

## 14. CLI

CLI 通过 Click 暴露常用本地流程：

```bash
codewiki repos add .
codewiki repos list
codewiki analyze .
codewiki update .
codewiki graphrag build . --embeddings
codewiki wiki catalog .
codewiki wiki pages .
codewiki wiki update . --language en
codewiki wiki page overview .
codewiki ask "How does page generation work?"
```

CLI 和 API 共享同一组 service 和 `CodeWikiStore`，数据库后端由 `CODEWIKI_DATABASE_URL`
决定，默认仍是 SQLite。

## 15. 错误处理和降级策略

| 场景 | 策略 |
|---|---|
| repo 不存在 | 404 |
| 业务前置条件缺失 | 400，例如未分析就 GraphRAG retrieve |
| LLM provider 调用失败 | 记录 `llm_run(status=error)`，API 返回 502 或 Wiki page draft |
| LLM JSON 非法 | repair payload 重试；最终失败则 draft 或 400 |
| source_refs 非法 | 页面 draft，错误写入 markdown |
| Mermaid 非法 | 过滤坏图；仍失败则移除图表保留正文 |
| community naming 失败 | analysis 成功，naming result 标记 failed/partial |
| incremental 无变更 | analysis_run 记录 done，复用旧 graph/chunks/pages |
| PostgreSQL pgvector 不可用 | 保留关系型数据和文本检索，vector hits 返回空列表 |

## 16. 当前已知约束

1. Wiki 的“Agent 工具调用”目前是 orchestrated evidence 模式：服务端强制注入 ReadFile
   evidence，但还不是 pydantic-ai 那种可自主循环调用工具的 Agent。
2. GraphRAG retrieval traces 当前通过 stable trace id 返回，但 `/graphrag/traces/{trace_id}` 尚未持久化。
3. Embedding vector search 是可选路径：SQLite 依赖 `sqlite-vec`，PostgreSQL 依赖数据库端
   pgvector extension；不可用时 GraphRAG 主要依赖 symbol、FTS 和 graph expansion。
4. LLM task routing 已支持 per-task profile，但 fallback models 字段还没有执行级 fallback。
5. 前端 HTML/Obsidian export 基于当前已加载 wiki 数据，不会主动向后端补拉缺失语言或页面。
6. Parser 覆盖了多语言常见结构，但跨文件调用解析仍是启发式，不做完整类型推导。

## 17. 后续优化路线

### P0: 稳定性和可观测性

- 持久化 GraphRAG traces，便于回放问答和 Wiki 生成上下文。
- 在 UI 中展示更细的 LLM run 链路：页面对应 run、provider usage、错误原因。
- 为 provider 错误增加可配置 retry/backoff 和 per-task fallback model。

### P1: Wiki Agent 化

- 引入显式工具调用接口：ListFiles、ReadFile、Grep、GraphQuery。
- Page generation 从“单次 payload + ReadFile evidence”演进为 bounded agent loop。
- 复杂 catalog item 可递归拆成子模块，并写回 catalog tree。

### P1: 增量更新精细化

- 区分 graph topology changed、source only changed、metadata changed。
- 对 translated pages 保存 source page hash，避免仅凭 slug 和 status 判断。
- 对 changed chunks 做 embedding 局部更新，而不是只刷新 chunk rows。

### P2: 前端图谱扩展

- 对大图增加分页或服务端按需 graph slice。
- 将 community、directory、file、symbol 多层 drilldown 做得更一致。
- 增加 graph layout cache 持久化。

### P2: 导出增强

- HTML export 增加离线 Mermaid 渲染失败提示。
- Obsidian export 可选择是否带 source refs、graph refs、frontmatter。
- 支持多语言一次性导出。

## 18. 实现原则

1. 确定性事实优先。能由 scanner/AST/graph 得出的信息，不交给 LLM 猜。
2. LLM 输出必须可追踪。所有 catalog/page/qa/community 调用都要记录 run、cache key 和 prompt version。
3. 失败要可恢复。单页失败不应拖垮整批 Wiki；单个 Mermaid 图失败不应拖垮正文。
4. 文档面向阅读，不面向文件树复刻。Catalog 应按用户理解路径拆分，而不是机械列目录。
5. 组件边界优先。API 适配、分析管线、GraphRAG、Wiki orchestration、LLM operation、前端导出分别演进。
