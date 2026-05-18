# CodeWiki

[English](README.md)

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
CODEWIKI_LLM__TIMEOUT_SECONDS=120
CODEWIKI_LLM__MAX_RETRIES=3
CODEWIKI_LLM__CACHE_ENABLED=true
```

每类 LLM 任务都可以单独覆盖 model、provider type、endpoint 和 API key：

```bash
# 快速/低成本的目录规划
CODEWIKI_LLM__PROFILES__CATALOG__MODEL=
CODEWIKI_LLM__PROFILES__CATALOG__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__CATALOG__ENDPOINT=
CODEWIKI_LLM__PROFILES__CATALOG__API_KEY=

# 更强的、带源码依据的 Wiki 页面生成
CODEWIKI_LLM__PROFILES__PAGE__MODEL=
CODEWIKI_LLM__PROFILES__PAGE__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__PAGE__ENDPOINT=
CODEWIKI_LLM__PROFILES__PAGE__API_KEY=

# 翻译
CODEWIKI_LLM__PROFILES__TRANSLATION__MODEL=
CODEWIKI_LLM__PROFILES__TRANSLATION__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__TRANSLATION__ENDPOINT=
CODEWIKI_LLM__PROFILES__TRANSLATION__API_KEY=

# Ask / QA
CODEWIKI_LLM__PROFILES__QA__MODEL=
CODEWIKI_LLM__PROFILES__QA__PROVIDER_TYPE=
CODEWIKI_LLM__PROFILES__QA__ENDPOINT=
CODEWIKI_LLM__PROFILES__QA__API_KEY=

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

# Wiki 生成
codewiki wiki catalog .
codewiki wiki pages .
codewiki wiki update . --language en
codewiki wiki page overview .

# 增量图更新，默认会启用 Wiki 重新生成
codewiki update .

# 基于 GraphRAG 的问答
codewiki ask "How does the main workflow fit together?"
codewiki ask --repo my-repo "Where are wiki pages generated?"
```

大多数命令都接受仓库 id、id 前缀、注册名、路径或 Git URL。
需要机器可读输出时，可以为 CLI 命令添加 `--json`。

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
