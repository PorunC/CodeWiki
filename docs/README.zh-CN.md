# CodeWiki

[English](../README.md)

CodeWiki 是一个面向单用户的本地代码知识平台，用于基于 AST 的代码图分析、
GraphRAG 检索、带源码依据的 Wiki 生成，以及由 LiteLLM 驱动的问答。

## 当前范围

- FastAPI 后端，提供仓库管理、分析运行、GraphRAG、Wiki、问答、图谱、
  文件、运行记录和设置 API。
- React/Vite 前端，包含仓库管理、图谱浏览器、Wiki 阅读器、问答和设置页面。
- 基于 AST 的代码图提取，支持 Python、TypeScript/TSX、JavaScript/JSX、
  Java、Go、Rust、C、C++ 和 C#。
- 确定性的图边提取，覆盖 imports、exports、definitions、inheritance、
  implementations、calls、route handlers、source references 和配置使用关系。
- GraphRAG 检索，包含源码块、可选 embeddings、社区摘要和 LLM 运行缓存。
- DeepWiki 风格的 Wiki 生成，包含目录规划、详细页面生成、源码引用、
  自动图表、多语言翻译和增量更新。
- 纯前端 Wiki 导出：可交互的独立 HTML 和 Obsidian vault ZIP。
- 设计说明位于 `docs/design.md`。

## 安装

从 PyPI 安装 Python 包：

```bash
pip install codewiki
codewiki --help
```

安装后启动 CodeWiki：

```bash
codewiki serve
```

然后打开 `http://127.0.0.1:8000` 使用 Web UI。Python 包已包含构建后的前端；
只有在需要使用 Vite 做前端开发时，才需要从源码仓库运行。

使用下面的命令配置本地环境变量：

```bash
codewiki config
codewiki config --set CODEWIKI_LLM__DEFAULT__MODEL=openai/gpt-4.1
codewiki config --profile qa --model openai/gpt-4.1 --api-key "$OPENAI_API_KEY"
codewiki config --list
```

## Wiki 工作流

1. 注册并分析一个仓库。
2. 构建 GraphRAG 源码块，可选启用 embeddings。
3. 生成 Wiki 目录。
4. 根据目录生成 Wiki 页面。
5. 代码变化后使用 update/regenerate 流程更新页面。

Wiki 页面基于确定性的代码图事实和检索到的源码块生成。页面提示词要求模型执行
gather/think/write 流程，并包含 ReadFile 证据，因此模型必须贴近真实源码文件。
源码引用会先经过校验，页面通过后才会提升为 `generated`；否则会以 `draft`
状态保存，并附带校验错误。

Mermaid 图由服务端根据已校验的图事实生成。无效图表会被过滤，而不会导致整个页面
生成失败，所以单个错误图块不会把可用页面变成草稿。

## Wiki 语言

基础 Wiki 语言会先生成。其他语言通过翻译基础目录和页面得到，同时保留 slugs、
源码引用、代码标识符、链接和 Markdown 结构。

在 `.env` 中配置翻译语言：

```bash
CODEWIKI_WIKI_BASE_LANGUAGE=en
CODEWIKI_WIKI_TRANSLATION_LANGUAGES=zh
```

前端 Wiki 页面在左侧目录上方提供 English/Chinese 语言切换。如果请求的非基础语言
不存在，后端会先生成基础 Wiki，然后再执行翻译。

## Wiki 导出

前端 Wiki 工具栏可以将当前选择的语言导出为：

- Interactive HTML：独立静态页面，包含目录导航、页面切换、Markdown 渲染、
  来源区块、相关页面和 Mermaid 渲染。
- Obsidian vault：ZIP 包，包含 Markdown 页面、Wiki 链接、源码元数据和最小化的
  `.obsidian` 设置。

导出完全在浏览器中基于已加载的 Wiki 数据完成，不需要后端导出 API。

## LLM 配置

运行 `codewiki config`，或复制 `.env.example` 并填写默认模型 profile：

```bash
cp .env.example .env
```

默认 profile 会用于所有任务，除非某个任务配置了专门的 profile 覆盖它。
下面是最简单的“所有任务使用同一个模型”配置：

```bash
CODEWIKI_LLM__MODE=sdk
CODEWIKI_LLM__DEFAULT__MODEL=provider/strong-coding-model
CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE=
CODEWIKI_LLM__DEFAULT__ENDPOINT=
CODEWIKI_LLM__DEFAULT__API_KEY=
# 可选的全局输出 token 上限。留空使用任务默认值；设为 0 则不向 provider 传 max_tokens。
# CODEWIKI_LLM__DEFAULT__MAX_TOKENS=0
CODEWIKI_LLM__TIMEOUT_SECONDS=120
CODEWIKI_LLM__MAX_RETRIES=3
CODEWIKI_LLM__CACHE_ENABLED=true
```

GraphRAG 检索上下文会直接影响 Wiki 页面生成可用的源码证据量。模型上下文窗口足够时，
可以在 `.env` 中调高这些值，让 Wiki 页面更深入：

```bash
CODEWIKI_GRAPHRAG_CONTEXT_TOKEN_BUDGET=8000
CODEWIKI_GRAPHRAG_MAX_SOURCE_CHUNKS=20
```

每类 LLM 任务都可以单独覆盖 model、provider type、endpoint、API key 和最大输出 token 数：

```bash
# 快速/低成本的目录规划。大型 DeepWiki catalog 可以调高这个值。
CODEWIKI_LLM__PROFILES__CATALOG__MODEL=
CODEWIKI_LLM__PROFILES__CATALOG__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__CATALOG__ENDPOINT=
CODEWIKI_LLM__PROFILES__CATALOG__API_KEY=
CODEWIKI_LLM__PROFILES__CATALOG__MAX_TOKENS=12000

# 更强的、带源码依据的 Wiki 页面生成
CODEWIKI_LLM__PROFILES__PAGE__MODEL=
CODEWIKI_LLM__PROFILES__PAGE__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__PAGE__ENDPOINT=
CODEWIKI_LLM__PROFILES__PAGE__API_KEY=
CODEWIKI_LLM__PROFILES__PAGE__MAX_TOKENS=12000

# 翻译
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
# 设为 0 可以避免给流式 QA 强制传 max_tokens。
CODEWIKI_LLM__PROFILES__QA__MAX_TOKENS=0

# Embeddings，在启用 GraphRAG 向量索引时使用
CODEWIKI_LLM__PROFILES__EMBEDDING__MODEL=
CODEWIKI_LLM__PROFILES__EMBEDDING__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__EMBEDDING__ENDPOINT=
CODEWIKI_LLM__PROFILES__EMBEDDING__API_KEY=
```

Provider 示例取决于 LiteLLM。对于 OpenAI-compatible endpoint，需要配置 endpoint
和 API key。对于 LiteLLM 原生 provider，请按照 LiteLLM 的 provider 命名规则配置
`PROVIDER_TYPE` 和 model。

失败的 LLM provider 调用会以 `status=error` 记录到 `llm_run`；API 响应会尽可能
返回 `run_id`，便于排查失败原因，同时不会暴露 API key。

## 开发

```bash
# 安装后端和前端依赖
make install

# 启动 FastAPI 和 Vite
make start

# 停止配置端口上的本地开发服务
make kill
```

默认本地 URL：

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

常用检查：

```bash
make lint
make test
make build
```

## CLI

```bash
# 注册或查看仓库
codewiki repos add . --name my-repo
codewiki repos list
codewiki repos scan .

# 完整分析和 GraphRAG
codewiki analyze .
codewiki graphrag build .
codewiki graphrag build . --embeddings

# 符号和图谱智能查询
codewiki graph search "AuthService"
codewiki graph callers generate_page
codewiki graph impact GraphRAGRetriever
codewiki graph explore "wiki page generation"
git diff --name-only | codewiki graph affected --stdin

# Wiki 生成
codewiki wiki catalog .
codewiki wiki pages .
codewiki wiki update . --language en
codewiki wiki page overview .

# 增量图更新，默认会启用 Wiki 重新生成
codewiki update .
codewiki watch .

# 基于 GraphRAG 的问答
codewiki ask "How does the main workflow fit together?"
codewiki ask --repo my-repo "Where are wiki pages generated?"

# 面向本地 AI 助手的 MCP server
codewiki mcp
# 或：codewiki-mcp

# Lite Mode：项目本地、无 LLM 的 agent 索引
codewiki lite index .
codewiki lite query AuthService
codewiki lite context "how authentication works"
codewiki lite trace LoginForm createSession
codewiki lite affected src/auth.py
codewiki mcp --lite --path .
```

大多数命令都接受仓库 id、id 前缀、注册名、路径或 Git URL。
需要机器可读输出时，可以为 CLI 命令添加 `--json`。

## Lite Mode

Lite Mode 面向本地 AI 助手和脚本。它在项目内创建
`.codewiki/codewiki-lite.sqlite3`，复用 CodeWiki 的 AST 图谱事实，但跳过 LLM 调用、
Wiki 生成、GraphRAG chunk 构建、PostgreSQL 和 Web UI 流程。适合把 CodeWiki 当作
本地代码智能索引使用。

```bash
# 初始化或重建本地 lite 索引
codewiki lite init .
codewiki lite index .

# 查看新鲜度并更新索引
codewiki lite status .
codewiki lite sync .
codewiki lite watch .

# 搜索和读取索引内容
codewiki lite query AuthService
codewiki lite files .
codewiki lite files . --tree
codewiki lite node generate_page
codewiki lite context "wiki page generation"

# 关系和影响分析
codewiki lite callers generate_page
codewiki lite callees GraphRAGRetriever
codewiki lite impact GraphRAGRetriever
codewiki lite trace WikiGenerator PageGenerator
git diff --name-only | codewiki lite affected --stdin

# 删除项目内 lite 索引
codewiki lite uninit . --force
```

`codewiki lite files` 默认从索引读取文件结构，便于 AI 助手快速查看已知项目树；
需要实时扫描文件系统时可以加 `--live`。

`codewiki lite status` 会报告索引是否落后于文件系统；JSON 输出包含 changed/new/deleted
文件列表。`codewiki lite sync` 执行一次增量更新，`codewiki lite watch` 用轮询方式保持
图谱新鲜，并且不会生成 Wiki 页面或源码 chunk。

Lite Mode 也可以通过 MCP 暴露：

```bash
# 为当前项目配置 Claude Code，并为 Codex CLI 写入全局配置
codewiki lite agents install . --target claude --location local
codewiki lite agents install . --target codex --location global
```

agent 安装器会写入 MCP server 配置、带标记的 CodeWiki Lite 使用说明，并在启用
`--auto-allow` 时写入 Claude Code 权限。可以用 `codewiki lite agents print-config
claude` 或 `codewiki lite agents print-config codex --location global` 只查看配置片段，
不写文件。

```json
{
  "mcpServers": {
    "codewiki-lite": {
      "command": "codewiki",
      "args": ["mcp", "--lite", "--path", "."]
    }
  }
}
```

`codewiki mcp --lite` 启动时会按需注册目标路径，并在服务工具前自动 catch up 已有索引。
如果不希望启动时同步，可以传 `--no-sync`。Lite MCP 工具包含 `codewiki_context`、
`codewiki_trace`、`codewiki_node`、图谱搜索/调用方/被调用方/影响面/探索/状态、索引文件
和受影响文件分析。如果索引后文件发生变化，context 类 MCP 响应会包含 pending-sync 提示
和受影响路径。

## MCP Server

CodeWiki 可以作为本地 stdio MCP server 运行，让 AI 助手通过工具访问已分析的仓库
图谱和 Wiki：

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

MCP server 暴露的工具覆盖仓库注册/列表、AST 分析、GraphRAG 索引构建和检索、
LLM 问答、图谱搜索/探索、受影响文件分析，以及已生成 Wiki 页面的读取。

## HTTP API 摘要

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/repos/{repo_id}/wiki/catalog?language=en` | 生成 Wiki 目录 |
| `POST` | `/api/repos/{repo_id}/wiki/pages/generate?language=en` | 生成全部 Wiki 页面 |
| `POST` | `/api/repos/{repo_id}/wiki/pages/update?language=en` | 增量生成过期或缺失的页面 |
| `POST` | `/api/repos/{repo_id}/wiki/pages/{slug}/regenerate?language=en` | 重新生成单个页面 |
| `POST` | `/api/repos/{repo_id}/wiki/translate` | 翻译目录和页面 |
| `GET` | `/api/repos/{repo_id}/wiki?language=en` | 读取 Wiki 目录和页面 |
| `POST` | `/api/repos/{repo_id}/ask` | 提出基于 GraphRAG 的问题 |
| `GET` | `/api/repos/{repo_id}/graph/search?q=...` | 搜索已索引符号 |
| `GET` | `/api/repos/{repo_id}/graph/callers?symbol=...` | 查找调用方/引用方 |
| `GET` | `/api/repos/{repo_id}/graph/callees?symbol=...` | 查找被调用/被引用目标 |
| `GET` | `/api/repos/{repo_id}/graph/impact?symbol=...` | 分析变更影响面 |
| `POST` | `/api/repos/{repo_id}/graph/explore` | 生成按源码文件聚合的探索上下文 |
| `POST` | `/api/repos/{repo_id}/graph/affected` | 查找受影响文件、测试和 Wiki 页面 |

## 支持的 AST 语言

| 语言 | Parser | 提取的事实 |
|---|---|---|
| Python | tree-sitter capture parser | imports、classes、functions、methods、decorators、calls、references、FastAPI-style endpoints |
| TypeScript / TSX | tree-sitter capture parser | imports/exports、classes、interfaces、type aliases、functions、methods、calls、route endpoints |
| JavaScript / JSX | tree-sitter capture parser | imports/exports、classes、functions、methods、calls、route endpoints |
| Java | tree-sitter capture parser | package/imports、classes、interfaces、records、enums、methods、constructors、inheritance、implementations、Spring-style endpoints |
| Go | tree-sitter capture parser | package/imports、structs、interfaces、type aliases、functions、receiver methods、calls、router-style endpoints |
| Rust | tree-sitter capture parser | imports、structs、enums、traits、impls、functions、methods、calls |
| C | tree-sitter capture parser | includes、structs、functions、calls |
| C++ | tree-sitter capture parser | includes、classes、structs、functions、methods、inheritance、calls |
| C# | tree-sitter capture parser | usings、namespaces、classes、interfaces、methods、inheritance、calls |

## 说明

核心约定是：代码事实首先来自确定性的扫描器和 AST 解析器。GraphRAG 和 LLM 工作流
消费这些事实来完成检索、综合和 Wiki 生成，而不是凭空创造结构。
