---
name: codewiki
description: Use this skill when the user wants Codex to generate or refresh CodeWiki wiki pages from local repository evidence without relying on CodeWiki's external LLM-backed wiki generator.
---

# CodeWiki

Use this skill when the user wants Codex to generate or refresh CodeWiki wiki pages from local repository evidence without relying on CodeWiki's external LLM-backed wiki generator.

## Workflow

1. Make sure the repository is registered and analyzed:
   - `codewiki repos add <path-or-url> --json`
   - `codewiki analyze <repo> --json`
2. Generate the wiki catalog without CodeWiki's LLM API:
   - `codewiki wiki catalog-evidence <repo> --language en --json`
   - Write a DeepWiki-style catalog JSON object with `title` and `items`.
   - Include `Overview`, `Architecture`, `Reading Guide`, and `Dependencies`.
   - Use real source hints from `catalog_evidence.module_candidates`, `repository_context`, and `source_chunks`.
   - Save it with `codewiki wiki catalog-save <repo> --language en --stdin --json`.
   - Validate it with `codewiki wiki catalog-validate <repo> --language en --json`.
3. Plan the wiki queue:
   - `codewiki wiki plan <repo> --language en --json`
4. For each page slug, fetch compact evidence:
   - `node <skill-dir>/scripts/compact-evidence.mjs <slug> <repo> --language en --limit 8`
   - Use a lower `--limit` for simple pages. Raise it only when validation or obvious gaps require more evidence.
   - Fall back to `codewiki wiki evidence <slug> <repo> --language en --limit 5 --json` only when the compact script is unavailable.
5. Write Markdown using only the compact evidence.
   - Cite claims with `[[S#]]` citation IDs from `allowed_source_refs`.
   - Follow `references/page-style.md` for page shape.
   - Start with `# <title>` and `## Purpose and Scope`.
   - Include at least one implementation detail section after Purpose and Scope.
   - Prefer evidence-backed tables for key files, components, workflows, APIs/data contracts, configuration, or failure modes.
   - Do not add `Sources`, `Relevant source files`, `Related Pages`, or Mermaid sections.
6. Save the page:
   - `codewiki wiki save <slug> <repo> --language en --title "<title>" --stdin --json`
7. Validate and repair until valid:
   - `codewiki wiki validate <slug> <repo> --language en --json`
8. Export the generated wiki to one standalone HTML file:
   - `node <skill-dir>/scripts/export-html.mjs <repo> --language en --output codewiki-wiki.html`

`<skill-dir>` is this skill folder. In a default Codex install it is usually `$CODEX_HOME/skills/codewiki`.

## MCP Tools

When CodeWiki MCP is available, prefer these tools for catalog planning, page planning, saving, and validation:

- `codewiki_wiki_catalog_evidence`
- `codewiki_wiki_catalog_save`
- `codewiki_wiki_catalog_validate`
- `codewiki_wiki_plan`
- `codewiki_wiki_page_save`
- `codewiki_wiki_page_validate`

For page evidence, prefer `scripts/compact-evidence.mjs` because raw MCP evidence can be too large for the agent context. Use `codewiki_wiki_evidence` only as a fallback with `limit <= 5`, then keep only `page`, `catalog_context`, `writing_brief`, `allowed_source_refs`, and short `source_chunks.content` excerpts before writing.

Always save and validate the catalog before requesting page evidence. Always fetch compact evidence and read `references/page-style.md` before writing a page. Do not paste full `retrieval_trace.context`, `context_pack`, large chunk bodies, or unrelated nodes into the conversation. Do not invent source claims, file paths, APIs, wiki pages, or architecture facts that are absent from the catalog/page evidence packs.
