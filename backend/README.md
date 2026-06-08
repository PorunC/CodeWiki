# @misaka09982/code-wiki

TypeScript backend for CodeWiki. It provides the HTTP API, CLI commands, stdio
MCP server, SQLite storage, repository scanning, lightweight graph analysis,
wiki drafts, source-grounded Q&A endpoints, and optional OpenAI-compatible Q&A
answers plus wiki catalog/page generation with cached LLM runs.

## Install

```bash
npm install -g @misaka09982/code-wiki
```

This installs three binaries:

- `codewiki`: main CLI for repositories, analysis, wiki, graph, Q&A, and server mode.
- `codewiki-backend`: alias for the same CLI, useful when another `codewiki` binary exists.
- `codewiki-mcp`: stdio MCP server for editor and agent integrations.

Check the install:

```bash
codewiki --version
codewiki --help
```

CodeWiki requires Node.js 22.13 or newer. SQLite storage uses Node's built-in
`node:sqlite` module, so Windows installs do not need Visual Studio Build Tools
or a native `better-sqlite3` compile step.

## First Run

Start the bundled web app and API:

```bash
codewiki serve
```

Then open:

```text
http://127.0.0.1:8000
```

From the UI you can register a repository, analyze it, inspect the graph, generate
wiki pages, and ask source-grounded questions.

By default CodeWiki stores data in a local SQLite database backed by
`node:sqlite`. You can choose a database location with:

```bash
export CODEWIKI_DATABASE_URL="sqlite:///$HOME/.codewiki/codewiki.sqlite3"
```

## CLI Walkthrough

Register the current repository:

```bash
cd /path/to/your/repo
codewiki repos add . --name my-repo
```

Run analysis:

```bash
codewiki analyze my-repo
```

Generate a provider-backed wiki catalog and pages after configuring catalog/page
LLM profiles:

```bash
codewiki wiki catalog my-repo
codewiki wiki pages my-repo
```

List and read generated pages:

```bash
codewiki wiki list my-repo
codewiki wiki read overview my-repo
```

Ask a question:

```bash
codewiki ask "How does the main request flow work?" my-repo
```

Inspect graph data:

```bash
codewiki graph status my-repo
codewiki graph search "handler" my-repo
codewiki graph explore my-repo --json
```

After code changes, refresh the index and regenerate stale wiki pages:

```bash
codewiki update my-repo
```

Most repository arguments accept a registered name, id, id prefix, filesystem path,
or Git URL. Add `--json` to most commands for machine-readable output.

## Agent-Generated Wiki

CodeWiki can also act as a local evidence engine for Codex, Claude Code, or other
agents. In this mode CodeWiki does not call an external LLM for catalog or page
writing. It returns bounded local evidence, lets the agent write the catalog and
Markdown, saves the results, and validates citations.

Install the Codex skill:

```bash
codewiki skill install codex
```

Then use the local workflow:

```bash
codewiki repos add . --name my-repo --json
codewiki analyze my-repo --json
codewiki wiki catalog-evidence my-repo --language en --json
# Write catalog JSON with title/items, then save it:
cat catalog.json | codewiki wiki catalog-save my-repo --language en --stdin --json
codewiki wiki catalog-validate my-repo --language en --json
codewiki wiki plan my-repo --language en --json
codewiki wiki evidence src my-repo --language en --json
printf '# Src\n\nThis page is grounded in returned evidence. [[S1]]\n' \
  | codewiki wiki save src my-repo --language en --title Src --stdin --json
codewiki wiki validate src my-repo --language en --json
codewiki wiki read src my-repo
```

Agents must cite returned `allowed_source_refs` with `[[S#]]`. Pages with missing
citations or unknown slugs are saved as drafts and reported by `wiki validate`.

Claude Code can use the same capability through `codewiki-mcp`. Configure the MCP
server and call:

- `codewiki_wiki_catalog_evidence`
- `codewiki_wiki_catalog_save`
- `codewiki_wiki_catalog_validate`
- `codewiki_wiki_plan`
- `codewiki_wiki_evidence`
- `codewiki_wiki_page_save`
- `codewiki_wiki_page_validate`

## LLM Configuration

CodeWiki works without an LLM: analysis, graph search, deterministic retrieval, and
basic wiki drafts still run locally. To enable provider-backed answers, community
names, wiki catalogs, and richer pages, configure an OpenAI-compatible profile:

```bash
codewiki config --init
codewiki config --model openai/gpt-4.1 --api-key "$OPENAI_API_KEY"
```

Or use environment variables:

```bash
export CODEWIKI_LLM__DEFAULT__MODEL="openai/gpt-4.1"
export CODEWIKI_LLM__DEFAULT__API_KEY="$OPENAI_API_KEY"
```

Use separate task profiles when you want different models for wiki pages, Q&A, or
community naming:

```bash
export CODEWIKI_LLM__PROFILES__CATALOG__MODEL="openai/gpt-4.1"
export CODEWIKI_LLM__PROFILES__CATALOG__API_KEY="$OPENAI_API_KEY"
export CODEWIKI_LLM__PROFILES__PAGE__MODEL="openai/gpt-4.1"
export CODEWIKI_LLM__PROFILES__PAGE__API_KEY="$OPENAI_API_KEY"
export CODEWIKI_LLM__PROFILES__COMMUNITY_SUMMARY__MODEL="openai/gpt-4.1"
export CODEWIKI_LLM__PROFILES__COMMUNITY_SUMMARY__API_KEY="$OPENAI_API_KEY"
```

Check configured values:

```bash
codewiki config list
codewiki config models
```

## Wiki Translation

Generate the base English wiki first, then translate to another language:

```bash
codewiki wiki pages my-repo --language en
codewiki wiki translate zh my-repo
codewiki wiki list my-repo --language zh
```

The web UI has language tabs for reading and generating wiki pages. When generating
a non-English wiki, CodeWiki ensures the base English pages exist and then stores
translated pages under the selected language.

## MCP Usage

Run the shared database MCP server:

```bash
codewiki-mcp
```

For editor projects, lite mode keeps a project-local database under `.codewiki/`:

```bash
codewiki mcp --lite --path .
```

`codewiki mcp --lite` uses a project-local `.codewiki/codewiki-lite.sqlite3`
database and registers the selected project automatically, which is convenient
for editor MCP clients that should not depend on a shared global CodeWiki DB.

You can also use lite mode directly from the CLI:

```bash
codewiki lite init --name my-repo
codewiki lite index
codewiki lite query "handler"
codewiki lite context "authentication flow"
codewiki lite status
```

## Common Commands

```bash
codewiki serve --host 127.0.0.1 --port 8000
codewiki repos list
codewiki repos tree --repo my-repo
codewiki files list --repo my-repo --source-only
codewiki graph affected my-repo src/main.ts --json
codewiki graphrag build my-repo
codewiki graphrag retrieve "startup flow" my-repo
codewiki wiki update my-repo
codewiki wiki page root my-repo
codewiki wiki translate zh my-repo
```

## Troubleshooting

- If `codewiki` is not found, ensure your npm global bin directory is on `PATH`.
  `npm bin -g` or `npm config get prefix` can help locate it.
- If `npm publish` or install commands mention scoped package access, use
  `npm publish --access public` for this package.
- If analysis finds too few files, check `.gitignore` and generated/vendor folders.
- If LLM-backed commands fall back to deterministic output, run `codewiki config list`
  and verify the model, endpoint, and API key.
- If the server port is busy, run `codewiki serve --port 8001`.

## Library Imports

The npm package can also be embedded from Node.js:

```js
import {
  createServer,
  CodeWikiStore,
  RepoScanner,
} from "@misaka09982/code-wiki";
import { CodeWikiMCPServer } from "@misaka09982/code-wiki/mcp";
```

## Development

```bash
npm install
npm run build
npm test
npm pack --dry-run
npm run pack:smoke
```

The package keeps the established CodeWiki SQLite table names where practical,
so existing local CodeWiki databases can be read by the TypeScript service.
