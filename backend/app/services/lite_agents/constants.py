CODEWIKI_LITE_SECTION_START = "<!-- CODEWIKI_LITE_START -->"
CODEWIKI_LITE_SECTION_END = "<!-- CODEWIKI_LITE_END -->"
CODEWIKI_LITE_SERVER_NAME = "codewiki-lite"

CODEWIKI_LITE_INSTRUCTIONS = f"""{CODEWIKI_LITE_SECTION_START}
## CodeWiki Lite

This project can use the CodeWiki Lite MCP server (`codewiki_*` tools). Lite Mode keeps
a project-local `.codewiki/codewiki-lite.sqlite3` index and skips LLM/wiki generation.

### When to prefer CodeWiki Lite

Use CodeWiki Lite for structural code questions: where a symbol is defined, what calls
it, what it calls, what may be affected by a change, and focused task context. Use text
search for literal strings, comments, log messages, or when you already know the file.

| Question | Tool |
|---|---|
| Find a symbol or file | `codewiki_graph_search` / `codewiki_files_tree` |
| What calls a symbol? | `codewiki_graph_callers` |
| What does a symbol call? | `codewiki_graph_callees` |
| What may change if I edit this? | `codewiki_graph_impact` / `codewiki_graph_affected` |
| Read a symbol and its source | `codewiki_node` |
| Get focused context for a task | `codewiki_context` |
| Check index freshness | `codewiki_graph_status` |

### Rules of thumb

- Prefer `codewiki_context` first for architecture or task exploration.
- Do not grep first when looking up symbols by name; the AST index is faster and typed.
- If the index is stale, run `codewiki lite sync .` or keep `codewiki lite watch .` running.
- If `.codewiki/` does not exist, ask before running `codewiki lite index .`.
{CODEWIKI_LITE_SECTION_END}"""

CLAUDE_LITE_PERMISSIONS = [
    "mcp__codewiki-lite__codewiki_files_tree",
    "mcp__codewiki-lite__codewiki_graph_search",
    "mcp__codewiki-lite__codewiki_graph_callers",
    "mcp__codewiki-lite__codewiki_graph_callees",
    "mcp__codewiki-lite__codewiki_graph_impact",
    "mcp__codewiki-lite__codewiki_graph_affected",
    "mcp__codewiki-lite__codewiki_context",
    "mcp__codewiki-lite__codewiki_node",
    "mcp__codewiki-lite__codewiki_graph_status",
]
