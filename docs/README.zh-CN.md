# CodeWiki

[English](../README.md) | [TypeScript Backend Architecture](typescript-backend.md)

CodeWiki 是一个面向单用户的本地代码知识平台，用于仓库分析、源码图检索、
Wiki 草稿生成和基于源码的本地问答。后端已经迁移到 `backend`，是一个可发布到
npm 的 TypeScript/Fastify 包，包名为 `@misaka09982/code-wiki`。

## 当前范围

- TypeScript/Fastify 后端，提供仓库管理、分析运行、图谱、Wiki、问答、文件、
  运行记录、设置 API 和 stdio MCP server。
- React/Vite 前端，包含仓库管理、图谱浏览器、Wiki 阅读器、问答和设置页面。
- SQLite 存储，沿用现有 CodeWiki 表名，覆盖仓库、分析运行、图节点/边、源码块、
  社区和 Wiki 页面。
- 支持本地路径和 Git URL 注册，处理 `.gitignore`，提供文件树 API 和轻量语言检测。
- 使用轻量确定性分析生成文件、定义、导入、调用、源码块、Wiki 草稿和本地问答上下文。
- LLM 环境变量会被读取并暴露给设置 API；问答、Wiki 目录和页面流程可选使用
  OpenAI-compatible chat completion provider 并记录缓存运行。provider-backed
  community generation、PostgreSQL、pgvector 和 tree-sitter 等深层能力是后续迁移项。

## 安装

从 npm 安装：

```bash
npm install -g @misaka09982/code-wiki
codewiki --help
```

启动服务：

```bash
codewiki serve
```

然后打开 `http://127.0.0.1:8000` 使用 Web UI。如果从源码仓库开发，使用
`make start` 同时启动 TypeScript 后端和 Vite 前端。

## 常用命令

```bash
codewiki repos add . --name my-repo
codewiki analyze my-repo
codewiki ask "How does the main workflow fit together?" my-repo
```

`codewiki wiki catalog` 和 `codewiki wiki pages` 是 provider-backed Wiki 生成路径，
需要先配置 catalog/page LLM profile。没有 CodeWiki LLM API 凭证时，使用 agent
工作流：

```bash
codewiki wiki catalog-evidence my-repo --json
codewiki wiki catalog-save my-repo --stdin --json < catalog.json
codewiki wiki plan my-repo --json
```

大多数仓库参数支持 id、id 前缀、已注册名称、路径或 Git URL。需要机器可读输出时
加 `--json`。

## 配置

默认使用 SQLite：

```bash
CODEWIKI_DATABASE_URL=sqlite:///./data/codewiki.sqlite3
```

TypeScript 后端也兼容旧的 Python SQLite URL 写法：

```bash
CODEWIKI_DATABASE_URL=sqlite+aiosqlite:///./data/codewiki.sqlite3
```

LLM 相关变量当前会被读取并暴露给设置 API。问答默认使用确定性的本地检索答案；
配置 QA/default LLM profile 后，会自动使用带缓存记录的 OpenAI-compatible chat
completion。Wiki 生成仍使用本地草稿实现：

```bash
CODEWIKI_LLM__MODE=sdk
CODEWIKI_LLM__DEFAULT__MODEL=provider/strong-coding-model
CODEWIKI_LLM__DEFAULT__API_KEY=
```

## Docker

```bash
docker compose up --build
```

Compose 会持久化 SQLite 数据库和存储缓存，并把当前仓库挂载到
`/workspace/CodeWiki`，可在 UI 或 CLI 中注册该路径。

## 开发

```bash
make install
make start
make lint
make typecheck
make test
make test-scripts
make lint-scripts
make build
make npm-pack
make npm-smoke
```

默认本地 URL：

- TypeScript 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`

## npm 包

可发布包位于 `backend`：

```bash
cd backend
npm run verify
npm run build
npm pack --dry-run
npm run pack:smoke
```

包入口：

- CLI：`codewiki`、`codewiki-backend`
- MCP：`codewiki-mcp`
- Library export：`@misaka09982/code-wiki`
- Server export：`@misaka09982/code-wiki/server`
- MCP export：`@misaka09982/code-wiki/mcp`

## MCP

npm 包内置 stdio MCP server：

```bash
codewiki-mcp
```

它通过 TypeScript 服务和当前 SQLite 数据库提供仓库、分析、图谱、GraphRAG 上下文、
Wiki 和问答工具。
