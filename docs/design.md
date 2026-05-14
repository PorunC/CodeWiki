# Code Wiki Platform — Design Document

## 1. 项目目标

构建一个单用户、本地优先的 Code Wiki 平台。输入代码仓库（本地目录或 Git URL），经过 AST 解析构建代码知识图谱，再通过 GraphRAG 和 LLM 生成结构化 Wiki 文档、调用关系图和代码问答。

平台重点不是多人协作，而是让开发者**快速理解一个陌生或复杂的代码库**。

## 2. 参考项目定位

| 项目 | 可借鉴点 |
|---|---|
| `CodeWiki` | 递归文档生成、叶子→模块总结、自底向上处理、prompt 模板分离 |
| `GitNexus` | 12 阶段 ingestion pipeline、tree-sitter 多语言提取、edge confidence 体系、Leiden community |
| `OpenDeepWiki` | repo→wiki 工作流、catalog/page 结构、源码约束 prompt、增量 diff 更新、Mermaid 图内联 |
| `Understand-Anything` | React Flow + ELK 分层布局、overview/detail 双层图、两阶段布局（atom + lazy per-container）、容器折叠 |
| `graphify` | 轻量 AST 抽取、双重提取（AST + LLM）、MinHash 去重、社区检测、多格式导出 |

不直接 fork 任一项目，融合其设计思想重新实现一个更轻、更聚焦的系统。

## 3. 产品范围

### 核心能力

- 导入本地仓库或 Git 仓库 URL
- 扫描文件并应用 `.gitignore` 规则
- 使用 tree-sitter 解析多语言代码结构
- 构建代码节点（文件、类、函数等）和关系边（调用、导入、继承等）
- 通过 Leiden/Louvain 算法进行社区检测
- 构建 code chunks + 向量索引
- GraphRAG 混合检索（符号匹配 + FTS + 向量 + 图扩展 + 社区摘要）
- LLM 生成 Wiki 目录和页面（Markdown + Mermaid）
- LLM 问答（带源码引用和图谱高亮）
- React Flow 展示代码图谱，ELK 分层布局，overview/detail 双层
- 增量更新：基于文件 hash 检测变更，局部重建

### 暂不做

- 多用户权限和团队协作
- 在线代码编辑
- SaaS 计费
- 完整 IDE 集成
- CI/CD 集成

## 4. 总体架构

```
Input (Local Dir / Git URL)
  → File Scanner (ignore · hash · classify)
  → AST Parser (tree-sitter, 12+ languages)
  → Graph Builder (nodes + edges + confidence tiers)
  → Community Detector (Leiden/Louvain + summaries)
  → [Chunk Builder → Embedding Index + FTS Index]
  → GraphRAG Retriever (hybrid: symbol + FTS + vector + graph expand + community)
  → LLM Generation (Catalog · Page · Q&A)
  → Storage (SQLite + Markdown files + Graph JSON)
  → FastAPI REST API
  → React Frontend (Doc Browser · Structure Graph · Ask Panel)
```

### 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12+ / FastAPI |
| AST 解析 | tree-sitter (原生绑定) |
| 图计算 | NetworkX |
| 社区检测 | graspologic (Leiden) → networkx (Louvain fallback) |
| 数据库 | SQLite (元数据) + FTS5 (全文搜索) |
| 向量索引 | sqlite-vec |
| LLM 抽象 | Anthropic / OpenAI / Azure OpenAI / AWS Bedrock |
| 前端 | Vite + React 19 + TypeScript |
| 图谱 UI | `@xyflow/react` v12 |
| 布局 | ELK.js (主) + dagre (fallback) |
| 状态管理 | Zustand |
| Markdown 渲染 | react-markdown + Mermaid |
| CLI | Python Click |

## 5. 后端模块

### 目录结构

```text
backend/
  app/
    main.py                    # FastAPI app + 路由注册
    config.py                  # 全局配置 (LLM、路径、数据库)
    api/
      repos.py                 # 仓库 CRUD
      graph.py                 # 图谱查询
      wiki.py                  # Wiki 生成和读取
      ask.py                   # 问答
      runs.py                  # 分析任务管理
    services/
      repo_scanner.py          # 仓库导入、ignore、文件 hash、语言识别
      ast_parser.py            # tree-sitter 多语言解析调度
      graph/                   # 构建统一 code graph
      community_detector.py    # Leiden/Louvain 社区检测 + 摘要
      chunk_builder.py         # 代码分块
      embedding_index.py       # 向量索引管理
      graphrag/                # 混合检索、图扩展、上下文打包
      wiki/                    # 生成 Wiki catalog 和 page
      llm_client.py            # 多后端 LLM 调用、重试、token 统计、缓存
      incremental/             # 文件变更检测、局部重建
    models/
      repo.py                  # ORM 模型
      graph.py                 # 图节点/边模型
      wiki.py                  # 文档模型
      rag.py                   # chunk/community/llm_run 模型
    schemas/
      graph.py                 # 图 API schema
      wiki.py                  # Wiki API schema
      ask.py                   # 问答 API schema
    prompts/
      catalog.md               # Catalog 生成 prompt
      page.md                  # 页面生成 prompt
      community_summary.md     # 社区摘要 prompt
      qa.md                    # 问答 prompt
```

### 核心服务职责

| 服务 | 职责 |
|---|---|
| `repo_scanner` | 仓库导入（本地/远程 clone）、文件遍历、ignore 规则、hash 计算、语言检测 |
| `ast_parser` | 使用 tree-sitter 提取符号、import、调用、类定义，输出统一 contract |
| `graph` | 合并 AST 输出为 NetworkX 有向图，区分 deterministic/inferred 边，写入 SQLite |
| `community_detector` | Leiden/Louvain 社区检测（算法）、递归分裂过大社区、LLM 生成社区摘要 |
| `chunk_builder` | 按函数/类/文件边界切分代码块，计算 token 数 |
| `embedding_index` | 将 code chunks 向量化存入 sqlite-vec |
| `graphrag` | 混合检索（符号匹配 + FTS5 + 向量相似度 + 图扩展 + 社区摘要召回），rerank，打包上下文 |
| `wiki` | 调用 LLM 生成 catalog（LLM 决定模块划分）和 page（Markdown 内容），校验 Mermaid 和源码引用 |
| `llm_client` | 统一 LLM 调用接口，指数退避重试，token 统计，相同输入 hash 命中缓存 |
| `incremental` | 比较文件 hash 检测变更，重解析变更文件，更新受影响的节点/边/page |

> **社区 (Community) vs 模块 (Module) 的区别：**
> - **Community** 由 `community_detector` 通过 Leiden/Louvain 算法自动发现，反映代码的结构性分组，用于 GraphRAG 检索增强。
> - **Module** 由 `wiki` 通过 LLM 在生成 Catalog 时决定，反映文档的逻辑章节划分，用于 Wiki 页面组织。
> - 两者可能重叠也可能不重叠——Community 是图结构上的，Module 是文档语义上的。

## 6. 数据模型

### SQLite Schema

```sql
-- 仓库
repo (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'local',  -- 'local' | 'git'
  git_url TEXT,
  commit_hash TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 分析运行记录
analysis_run (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id),
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  error TEXT
);

-- 代码节点
code_node (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id),
  type TEXT NOT NULL,  -- file | class | function | method | interface | endpoint | config | schema | module
  name TEXT NOT NULL,
  file_path TEXT NOT NULL,
  start_line INTEGER,
  end_line INTEGER,
  language TEXT,
  symbol_id TEXT,
  summary TEXT,
  hash TEXT NOT NULL,
  metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX idx_code_node_repo ON code_node(repo_id);
CREATE INDEX idx_code_node_type ON code_node(repo_id, type);
CREATE INDEX idx_code_node_file ON code_node(repo_id, file_path);

-- 代码关系边
code_edge (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id),
  source_id TEXT NOT NULL REFERENCES code_node(id),
  target_id TEXT NOT NULL REFERENCES code_node(id),
  type TEXT NOT NULL,  -- contains | imports | exports | defines | calls | inherits | implements | references | routes_to | uses_config
  confidence REAL NOT NULL DEFAULT 1.0,  -- 1.0 = deterministic, <1.0 = inferred
  weight REAL NOT NULL DEFAULT 1.0,
  is_inferred INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT DEFAULT '{}'
);
CREATE INDEX idx_code_edge_repo ON code_edge(repo_id);
CREATE INDEX idx_code_edge_source ON code_edge(source_id);
CREATE INDEX idx_code_edge_target ON code_edge(target_id);

-- 代码块 (用于向量检索)
code_chunk (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id),
  node_id TEXT REFERENCES code_node(id),
  file_path TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_code_chunk_repo ON code_chunk(repo_id);

-- 图社区
graph_community (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id),
  name TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 0,
  node_ids_json TEXT NOT NULL DEFAULT '[]',
  summary TEXT,
  summary_hash TEXT
);
CREATE INDEX idx_graph_community_repo ON graph_community(repo_id);

-- Wiki 目录
doc_catalog (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id),
  title TEXT NOT NULL,
  structure_json TEXT NOT NULL DEFAULT '{"items":[]}',
  generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wiki 页面
doc_page (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id),
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  parent_slug TEXT,
  markdown TEXT NOT NULL DEFAULT '',
  source_refs_json TEXT DEFAULT '[]',
  graph_refs_json TEXT DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',  -- draft | generated | reviewed
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_doc_page_repo ON doc_page(repo_id);
CREATE UNIQUE INDEX idx_doc_page_slug ON doc_page(repo_id, slug);

-- LLM 调用记录
llm_run (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id),
  task_type TEXT NOT NULL,  -- catalog | page | qa | cluster | community_summary
  model TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'success',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_llm_run_task ON llm_run(repo_id, task_type, input_hash);
```

## 7. Code Graph 设计

### 节点类型

| 类型 | 说明 | 来源 |
|---|---|---|
| `repository` | 仓库根节点 | 自动生成 |
| `directory` | 目录 | 文件扫描 |
| `file` | 源文件 | 文件扫描 |
| `module` | 逻辑模块 | LLM 聚类或人工定义 |
| `class` | 类定义 | AST |
| `interface` | 接口/协议定义 | AST |
| `function` | 函数/方法定义 | AST |
| `method` | 类方法 | AST |
| `endpoint` | HTTP/RPC 端点 | AST + 框架检测 |
| `config` | 配置项 | AST + 启发式 |
| `schema` | 数据模型/类型定义 | AST |

### 边类型

| 类型 | 含义 | 分类 |
|---|---|---|
| `contains` | 目录→文件, 文件→类, 类→方法 | **deterministic** |
| `defines` | 文件→顶层定义 | **deterministic** |
| `imports` | 文件→导入的模块/文件 | **deterministic** |
| `exports` | 文件→导出的符号 | **deterministic** |
| `calls` | 函数→被调用的函数 | **deterministic** (文件内) / **inferred** (跨文件) |
| `inherits` | 类→父类/接口 | **deterministic** |
| `implements` | 类→实现的接口 | **deterministic** |
| `references` | 任意节点→引用的其他节点 | **inferred** |
| `routes_to` | endpoint→处理函数 | 框架检测 |
| `uses_config` | 函数→config 节点 | **inferred** |

### Edge Confidence 体系

借鉴 GitNexus 的设计，每条边都有 `confidence` 值和 `is_inferred` 标记：

- **deterministic** (`confidence=1.0, is_inferred=0`): AST 明确可得，如文件内调用、import 语句、继承声明。
- **inferred** (`confidence<1.0, is_inferred=1`): 启发式推断，如跨文件调用（通过名称模糊匹配）、配置使用关系。

前端将 `inferred` 边渲染为**虚线或低透明度**，用户可一键隐藏。

## 8. AST 解析流程

### 统一输出 Contract

```python
@dataclass
class AstSymbol:
    id: str                    # 唯一标识，如 "src/auth.py::login"
    type: str                  # file | class | function | method | interface
    name: str                  # 符号名
    file_path: str             # 相对路径
    language: str              # python | typescript | javascript | java | go | ...
    range: tuple[int, int]     # (start_line, end_line)
    parent_id: str | None      # 父节点 ID（如方法所属的类）
    signature: str | None      # 函数签名
    docstring: str | None      # 文档注释
    imports: list[str]         # 导入的模块路径列表（未解析的原始字符串）
    calls: list[str]           # 调用的函数名列表（未解析的原始字符串，跨文件解析由 graph_builder 完成）
    hash: str                  # 源码 hash（用于增量检测）
```

### 解析原则

1. 先保证**文件、目录、类、函数、import**准确。
2. 跨文件调用先用**启发式名称匹配**解析（后续可加 scope-resolution 流水线）。
3. 不在 MVP 阶段实现完整类型推导系统。
4. **每个节点必须能追溯到源文件和行号**。
5. 借鉴 graphify 的做法，每种语言配置独立的数据类，定义 `class_types`、`function_types`、`import_types`、`call_types` 和 `import_handler`。

### MVP 支持语言

TypeScript/JavaScript、Python、Java、Go。

后续扩展：C、C++、C#、Rust、Kotlin、Ruby、PHP、Swift。

## 9. GraphRAG 设计

GraphRAG 不是替代 AST，而是在 AST 图谱之上增强检索召回。

### 检索流程

```
Query → [Symbol Match] + [FTS5 Keyword] + [Vector Search]
  → Seed Nodes (候选起点)
  → Graph Expansion (沿边遍历, max 2 hops)
  → Community Summary 召回 (种子节点所属社区)
  → Source Chunks 收集
  → Rerank (加权排序)
  → Context Pack (结构化上下文)
```

### 混合排序公式

```
score = 0.35 * semantic_score
      + 0.25 * keyword_score
      + 0.20 * graph_proximity_score  (到种子节点的最短路径距离)
      + 0.10 * node_importance_score  (度中心性)
      + 0.10 * source_freshness_score (commit 时间)
```

### 上下文包结构

```json
{
  "query": "...",
  "seed_nodes": [{"id": "...", "type": "function", "name": "..."}],
  "expanded_nodes": [...],
  "related_edges": [...],
  "community_summaries": [
    {"name": "Auth Module", "summary": "Handles user authentication via JWT..."}
  ],
  "source_chunks": [
    {"file_path": "src/auth/login.py", "start_line": 35, "end_line": 82, "content": "..."}
  ],
  "source_refs": [
    {"file_path": "src/auth/login.py", "start_line": 35, "end_line": 82}
  ]
}
```

## 10. Wiki 生成流程

### 整体时序

```
Code Graph + Chunks + Communities
  → GraphRAG: build repo overview context
  → LLM: generate catalog (TOC)
  → For each catalog page topic:
      GraphRAG: retrieve focused context pack
      LLM: generate page markdown
  → Validate: Mermaid syntax, source refs
  → Save: doc_page to SQLite, .md to disk
```

### 页面模板

```markdown
# 模块名称

## 概述
（模块是什么，解决什么问题）

## 核心流程
（关键执行路径）

## 关键文件
（涉及的主要源文件列表，带链接）

## 主要类型与函数
（API 签名和用途说明）

## 调用关系
（Mermaid 图，基于真实 graph edges 生成）

## 配置与入口
（配置项、启动参数、环境变量）

## 注意事项
（陷阱、边界条件、设计约束）
```

### LLM 约束（借鉴 OpenDeepWiki）

1. **不允许编造不存在的 API**。所有代码说明必须来自 `source_chunks`。
2. **Mermaid 图必须来自真实 graph edges**。不虚构调用关系。
3. **代码示例必须来自真实源码**，或明确标注为伪代码。
4. **输出必须包含源码引用**：格式 `[文件名:L行号](source-link)`。
5. 不确定的内容标注 `[待确认]`，不强行提供答案。

### 文档校验

- 使用 `mermaid-parser-py` 校验所有 Mermaid 图语法。
- 校验 `source_refs` 中的文件路径和行号是否存在。
- 失败的页面标记 `status='draft'` 并记录错误。

## 11. API 设计

```http
# 仓库管理
POST   /api/repos                           # 创建仓库（本地路径或 Git URL）
GET    /api/repos                           # 列出所有仓库
GET    /api/repos/{repo_id}                 # 仓库详情
DELETE /api/repos/{repo_id}                 # 删除仓库

# 分析任务
POST   /api/repos/{repo_id}/analyze         # 触发分析
GET    /api/repos/{repo_id}/runs            # 分析任务列表
GET    /api/repos/{repo_id}/runs/{run_id}   # 分析任务状态

# 图谱
GET    /api/repos/{repo_id}/graph           # 完整图谱 (JSON)
GET    /api/repos/{repo_id}/graph/nodes/{node_id}  # 节点详情 + 邻接边
GET    /api/repos/{repo_id}/graph/edges            # 边列表 (支持 type/inferred 过滤)
GET    /api/repos/{repo_id}/communities            # 社区列表
GET    /api/repos/{repo_id}/communities/{id}       # 社区详情 + 成员节点

# GraphRAG
POST   /api/repos/{repo_id}/graphrag/retrieve     # 检索上下文

# Wiki
POST   /api/repos/{repo_id}/wiki/catalog           # 生成目录
POST   /api/repos/{repo_id}/wiki/pages/generate    # 生成全部页面
POST   /api/repos/{repo_id}/wiki/pages/{slug}/regenerate  # 重新生成单页
GET    /api/repos/{repo_id}/wiki                    # 获取 Wiki 结构
GET    /api/repos/{repo_id}/wiki/pages/{slug}       # 获取页面内容

# 问答
POST   /api/repos/{repo_id}/ask                     # 问答
```

### 问答请求

```json
{
  "question": "登录流程是怎么实现的？",
  "mode": "graph_rag",
  "max_hops": 2,
  "include_sources": true,
  "include_graph": true
}
```

### 问答响应

```json
{
  "answer": "登录流程通过 AuthService.login() 方法实现...",
  "sources": [
    {"file_path": "src/auth/service.ts", "start_line": 35, "end_line": 82}
  ],
  "related_nodes": [
    {"id": "src/auth/service.ts::login", "type": "method"}
  ],
  "related_edges": [
    {"source": "...", "target": "...", "type": "calls"}
  ],
  "trace_id": "req_abc123"
}
```

## 12. 前端设计

### 页面路由

```text
/repos                           # 仓库列表
/repos/:id/wiki                  # Wiki 文档浏览
/repos/:id/graph                 # 代码图谱 (React Flow)
/repos/:id/files                 # 文件树 + 符号列表
/repos/:id/ask                   # 问答面板
/repos/:id/runs                  # 分析任务记录
/repos/:id/settings              # 仓库设置 (ignore、语言、模型)
```

### 主要视图

| 视图 | 功能 |
|---|---|
| **Wiki** | 左侧目录树，右侧渲染 Markdown + Mermaid，源码引用可点击跳转 |
| **Graph** | React Flow + ELK 分层布局，overview（模块级）和 detail（文件/函数级）双层 |
| **Files** | 文件树 + 符号列表 + 节点详情面板 |
| **Ask** | 问答输入，流式返回，相关图谱节点高亮，源码引用可点击 |

### Graph 视图设计（借鉴 Understand-Anything）

**双层结构：**

- **Overview Graph**：展示模块、目录、社区。节点为 cluster node，点击 drill-down 进入 detail 层。
- **Detail Graph**：展示文件、类、函数、方法。ELK layered 布局，文件夹/社区作为可折叠容器。

**两阶段 ELK 布局：**

- **Stage 1**：容器视为原子，运行 ELK 计算整体布局，容器间边聚合显示。
- **Stage 2**：用户展开容器时，仅对该容器内子节点运行 ELK，结果缓存到 `containerLayoutCache`。
- **偏差修正**：容器实际大小与 Stage 1 估算偏差 >20% 时，触发 Stage 1 重跑。

**交互特性：**

- 节点搜索（fuse.js 模糊搜索）
- 节点类型过滤（显示/隐藏 inferred 边）
- 点击节点打开详情面板（源码预览、邻接关系）
- GraphRAG 返回的相关节点自动高亮
- Overview ↔ Detail 导航面包屑

## 13. 增量更新

基于文件 hash 实现增量分析：

```
Rescan repo → Compare file hash with stored hash
  ├─ Changed files → Reparse AST → Update nodes/edges
  │   └─ Find affected pages (by source_refs + graph neighbors)
  │       └─ Mark pages for regeneration
  ├─ New files → Parse AST → Add nodes/edges
  ├─ Deleted files → Mark nodes stale → Clean orphan edges
  └─ Unchanged files → Reuse cache (AST, chunks, embeddings)
```

更新策略：

- 文件未变：复用 AST 结果、chunk、embedding、文档摘要。
- 文件变更：重建相关节点、边、chunk、embedding。
- 文件删除：标记节点失效并清理相关边。
- 文档更新：根据 `source_refs` 和 graph 邻居定位受影响页面，仅重新生成受影响的页面。

借鉴 CodeWiki 的做法，`metadata.json` 记录上次分析的 commit hash，通过 `git diff` 定位变更文件列表。

## 14. LLM 客户端设计

### 多后端抽象

```python
BACKENDS = {
    "anthropic":   {"base_url": "https://api.anthropic.com", "default_model": "claude-sonnet-4-6"},
    "openai":      {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o"},
    "azure":       {"base_url": "https://{resource}.openai.azure.com", "default_model": "gpt-4o"},
    "bedrock":     {"base_url": None, "default_model": "anthropic.claude-sonnet-4-6-v1"},
    "ollama":      {"base_url": "http://localhost:11434/v1", "default_model": "llama3.2"},
}
```

### 不同任务使用不同模型

借鉴 OpenDeepWiki 的分模型配置：

| 任务 | 推荐模型 | 原因 |
|---|---|---|
| Catalog 生成 | 便宜快速模型 (gpt-4o-mini) | 结构归纳，不需要深度推理 |
| Page 生成 | 强模型 (Claude Sonnet 4.6) | 需要理解代码细节 |
| Community 摘要 | 便宜模型 | 批量处理，输入小 |
| Q&A | 强模型 | 需要精确回答 |
| 模块聚类 | 便宜模型 | 输入为路径+名称列表 |

### 缓存策略

- 基于 `(model, task_type, input_hash)` 做 LLM 调用缓存。
- AST 提取结果缓存到 `storage/cache/ast/{sha256}.json`（借鉴 graphify）。
- Embedding 按 `content_hash` 去重，避免重复计算。

### 自适应上下文重试

借鉴 graphify：如果 LLM 响应被截断（`finish_reason == "length"`）或因上下文窗口错误失败，递归地将输入对半分割并重试，最多 3 层深度。

## 15. MVP 路线

| 阶段 | 内容 | 里程碑 |
|---|---|---|
| **P1** | 仓库扫描、文件分类、语言检测、tree-sitter AST 解析、节点/边入库 | 能对 Python/TS 项目生成 code graph |
| **P2** | Code graph API (`/api/repos/{id}/graph`)，节点查询、边过滤 | 通过 API 获取图谱 JSON |
| **P3** | React Flow 前端：overview graph（模块级）、detail graph（文件/函数级）、ELK 布局 | 浏览器中可视化浏览图谱 |
| **P4** | Code chunks 构建、embedding 索引、FTS5 全文搜索、GraphRAG 混合检索 | 能按语义搜索代码 |
| **P5** | LLM Wiki 生成：catalog → page，Markdown + Mermaid，源码引用校验 | 自动生成完整 Wiki 文档 |
| **P6** | 页面校验、Mermaid 语法检查、source refs 验证、单页重新生成 | 文档质量有保障 |
| **P7** | Ask 问答、流式返回、图谱联动高亮、源码引用 | 能用自然语言问代码问题 |
| **P8** | 增量更新（文件 hash 检测）、LLM 缓存、大仓库性能优化 | 实用化 |

## 16. 关键风险与应对

| 风险 | 应对 |
|---|---|
| AST 图谱不准（多语言解析差异大） | 先支持 4 种语言做扎实；区分 deterministic/inferred 边 |
| LLM 幻觉（编造不存在的 API） | Prompt 强制 source refs；输出校验文件路径和行号 |
| 大仓库性能差（10万+ 节点） | 增量 hash 跳过未变文件；图谱分页/懒加载；community 折叠 |
| 图谱可视混乱（边太多） | overview/detail 双层；edge confidence 过滤；默认隐藏 inferred 边 |
| GraphRAG 召回噪声 | 混合排序（symbol + FTS + vector + graph proximity）；可调权重 |
| 多语言解析复杂度 | 插件式 parser 注册；每种语言独立配置类；逐步扩展 |
| LLM 成本过高 | 输入 hash 缓存；小模型做聚类/摘要，大模型做内容生成 |

## 17. 实现原则

1. **先做准，再做全。** 第一版最重要的：AST 节点真实可靠、每个文档段落可追溯源码、GraphRAG 返回证据链。
2. **AST 解析保证事实，Code Graph 表达结构，GraphRAG 负责召回上下文，LLM 负责总结和组织，React Flow 负责可视化理解。** 每个组件职责清晰。
3. **LLM 只负责总结和组织，不负责猜测事实。** 所有代码事实必须来自 AST 或源码。
4. **确定性优先于智能。** 能用 AST 得出的结论，不交给 LLM。
5. **借鉴但不照搬。** 参考 CodeWiki 的管道、GitNexus 的社区检测、OpenDeepWiki 的 prompt 约束、Understand-Anything 的布局策略、graphify 的缓存设计。
