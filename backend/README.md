# codewiki-backend

TypeScript backend for CodeWiki. It provides the HTTP API, CLI commands, stdio
MCP server, SQLite storage, repository scanning, lightweight graph analysis,
wiki drafts, source-grounded Q&A endpoints, and optional OpenAI-compatible Q&A
answers plus wiki catalog/page generation with cached LLM runs.

```bash
npm install -g codewiki-backend
codewiki serve
codewiki-mcp
codewiki mcp --lite --path .
```

`codewiki mcp --lite` uses a project-local `.codewiki/codewiki-lite.sqlite3`
database and registers the selected project automatically, which is convenient
for editor MCP clients that should not depend on a shared global CodeWiki DB.

Development:

```bash
npm install
npm run build
npm test
npm pack --dry-run
npm run pack:smoke
```

The package keeps the established CodeWiki SQLite table names where practical,
so existing local CodeWiki databases can be read by the TypeScript service.
