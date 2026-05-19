from __future__ import annotations

from backend.app.database import SQLiteStore
from backend.app.mcp_server import handlers
from backend.app.mcp_server.types import ToolSpec
from backend.app.mcp_server.utils import object_schema


def build_tools(store: SQLiteStore) -> dict[str, ToolSpec]:
    tools = [
        ToolSpec(
            name="codewiki_repos_list",
            description="List repositories registered in the local CodeWiki database.",
            input_schema=object_schema({}),
            handler=lambda args: handlers.repos_list(store, args),
        ),
        ToolSpec(
            name="codewiki_repo_add",
            description="Register a local repository path or Git URL in CodeWiki.",
            input_schema=object_schema(
                {
                    "path": {"type": "string", "description": "Local path or Git URL."},
                    "name": {"type": "string", "description": "Optional display name."},
                    "source_type": {
                        "type": "string",
                        "description": "Repository source type.",
                        "default": "local",
                    },
                },
                required=["path"],
            ),
            handler=lambda args: handlers.repo_add(store, args),
        ),
        ToolSpec(
            name="codewiki_analyze",
            description="Run AST graph analysis for a registered repo, path, name, or id.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "community_summaries": {
                        "type": "boolean",
                        "description": "Whether to generate LLM community summaries.",
                        "default": False,
                    },
                }
            ),
            handler=lambda args: handlers.analyze(store, args),
        ),
        ToolSpec(
            name="codewiki_graphrag_build",
            description="Build GraphRAG source chunks and optional embeddings for a repository.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "embeddings": {
                        "type": "boolean",
                        "description": "Whether to build vector embeddings.",
                        "default": False,
                    },
                }
            ),
            handler=lambda args: handlers.graphrag_build(store, args),
        ),
        ToolSpec(
            name="codewiki_retrieve_context",
            description="Retrieve GraphRAG context for a repository question without calling an LLM.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "query": {"type": "string", "description": "Question or topic to retrieve."},
                    "max_hops": {
                        "type": "integer",
                        "description": "Graph expansion hops from 0 to 4.",
                        "default": 2,
                    },
                    "include_embeddings": {
                        "type": "boolean",
                        "description": "Whether to include vector search.",
                        "default": False,
                    },
                },
                required=["query"],
            ),
            handler=lambda args: handlers.retrieve_context(store, args),
        ),
        ToolSpec(
            name="codewiki_ask",
            description="Ask a GraphRAG-grounded question using the configured LLM provider.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "question": {"type": "string", "description": "Question to answer."},
                    "max_hops": {
                        "type": "integer",
                        "description": "Graph expansion hops from 0 to 4.",
                        "default": 2,
                    },
                },
                required=["question"],
            ),
            handler=lambda args: handlers.ask(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_search",
            description="Search indexed code graph symbols by name, path, signature, or docstring.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "query": {"type": "string", "description": "Search query."},
                    "type": {"type": "string", "description": "Optional node type filter."},
                    "language": {"type": "string", "description": "Optional language filter."},
                    "path": {"type": "string", "description": "Optional path substring."},
                    "name": {"type": "string", "description": "Optional name substring."},
                    "limit": {"type": "integer", "default": 20},
                },
            ),
            handler=lambda args: handlers.graph_search(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_explore",
            description="Build source-section exploration context for a query.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "query": {"type": "string", "description": "Exploration query."},
                    "max_files": {"type": "integer", "default": 12},
                    "max_nodes": {"type": "integer", "default": 160},
                },
                required=["query"],
            ),
            handler=lambda args: handlers.graph_explore(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_affected",
            description="Find files, tests, and wiki pages affected by changed files.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Changed file paths relative to the repo.",
                    },
                    "depth": {"type": "integer", "default": 5},
                    "test_glob": {"type": "string", "description": "Optional test file glob."},
                },
                required=["file_paths"],
            ),
            handler=lambda args: handlers.graph_affected(store, args),
        ),
        ToolSpec(
            name="codewiki_wiki_pages_list",
            description="List generated wiki pages for a repository.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "language": {"type": "string", "default": "en"},
                }
            ),
            handler=lambda args: handlers.wiki_pages_list(store, args),
        ),
        ToolSpec(
            name="codewiki_wiki_page_read",
            description="Read a generated wiki page by slug.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "slug": {"type": "string", "description": "Wiki page slug."},
                    "language": {"type": "string", "default": "en"},
                },
                required=["slug"],
            ),
            handler=lambda args: handlers.wiki_page_read(store, args),
        ),
    ]
    return {tool.name: tool for tool in tools}
