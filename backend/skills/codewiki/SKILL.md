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
2. Plan the wiki queue:
   - `codewiki wiki plan <repo> --language en --json`
3. For each page slug, fetch evidence:
   - `codewiki wiki evidence <slug> <repo> --language en --json`
4. Write Markdown using only the returned evidence.
   - Cite claims with `[[S#]]` citation IDs from `allowed_source_refs`.
   - Follow `references/page-style.md` for page shape.
5. Save the page:
   - `codewiki wiki save <slug> <repo> --language en --title "<title>" --stdin --json`
6. Validate and repair until valid:
   - `codewiki wiki validate <slug> <repo> --language en --json`

## MCP Tools

When CodeWiki MCP is available, prefer these tools over shell commands:

- `codewiki_wiki_plan`
- `codewiki_wiki_evidence`
- `codewiki_wiki_page_save`
- `codewiki_wiki_page_validate`

Always call `evidence` before writing a page. Do not invent source claims, file paths, APIs, or architecture facts that are absent from the evidence pack.
