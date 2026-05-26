from __future__ import annotations

from backend.app.database import CodeWikiStore
from backend.app.mcp_server import handlers
from backend.app.mcp_server.types import ToolSpec
from backend.app.mcp_server.utils import object_schema


def build_tools(store: CodeWikiStore) -> dict[str, ToolSpec]:
    tools = [
        ToolSpec(
            name="codewiki_repos_list",
            description="List repositories registered in the local CodeWiki database.",
            input_schema=object_schema({}),
            handler=lambda args: handlers.repos_list(store, args),
        ),
        ToolSpec(
            name="codewiki_health",
            description="Check that the CodeWiki MCP server is reachable.",
            input_schema=object_schema({}),
            handler=lambda args: handlers.health(store, args),
        ),
        ToolSpec(
            name="codewiki_llm_models",
            description="Show configured LLM routing profiles and model settings.",
            input_schema=object_schema({}),
            handler=lambda args: handlers.llm_models(store, args),
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
            name="codewiki_repo_delete",
            description="Delete a registered repository and its indexed data.",
            input_schema=object_schema(
                {"repo": {"type": "string", "description": "Repo id, name, path, or Git URL."}},
                required=["repo"],
            ),
            handler=lambda args: handlers.repo_delete(store, args),
        ),
        ToolSpec(
            name="codewiki_repo_scan",
            description="Scan a local repository path or Git URL without registering it.",
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
            handler=lambda args: handlers.repo_scan(store, args),
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
                        "default": True,
                    },
                }
            ),
            handler=lambda args: handlers.analyze(store, args),
        ),
        ToolSpec(
            name="codewiki_update",
            description="Run an incremental graph update and optionally refresh chunks/wiki/community summaries.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "refresh_chunks": {"type": "boolean", "default": True},
                    "regenerate_wiki": {"type": "boolean", "default": True},
                    "community_summaries": {"type": "boolean", "default": True},
                }
            ),
            handler=lambda args: handlers.incremental_update(store, args),
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
            name="codewiki_files_tree",
            description="Scan a registered repository and return its file tree and file list.",
            input_schema=object_schema(
                {"repo": {"type": "string", "description": "Repo id, name, path, or Git URL."}}
            ),
            handler=lambda args: handlers.files_tree(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_dump",
            description="Return the full stored graph nodes, edges, communities, and community edges.",
            input_schema=object_schema(
                {"repo": {"type": "string", "description": "Repo id, name, path, or Git URL."}}
            ),
            handler=lambda args: handlers.graph_dump(store, args),
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
            name="codewiki_graph_callers",
            description="List graph nodes that call or reference a symbol.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "symbol": {"type": "string", "description": "Symbol name or id."},
                    "limit": {"type": "integer", "default": 20},
                },
                required=["symbol"],
            ),
            handler=lambda args: handlers.graph_callers(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_callees",
            description="List graph nodes called or referenced by a symbol.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "symbol": {"type": "string", "description": "Symbol name or id."},
                    "limit": {"type": "integer", "default": 20},
                },
                required=["symbol"],
            ),
            handler=lambda args: handlers.graph_callees(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_impact",
            description="Return the impact subgraph for changing a symbol.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "symbol": {"type": "string", "description": "Symbol name or id."},
                    "depth": {"type": "integer", "default": 2},
                },
                required=["symbol"],
            ),
            handler=lambda args: handlers.graph_impact(store, args),
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
            name="codewiki_graph_status",
            description="Show graph index statistics for a repository.",
            input_schema=object_schema(
                {"repo": {"type": "string", "description": "Repo id, name, path, or Git URL."}}
            ),
            handler=lambda args: handlers.graph_status(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_node_read",
            description="Read a graph node and its adjacent edges by node id.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "node_id": {"type": "string", "description": "Graph node id."},
                },
                required=["node_id"],
            ),
            handler=lambda args: handlers.graph_node_read(store, args),
        ),
        ToolSpec(
            name="codewiki_communities_list",
            description="List detected graph communities for a repository.",
            input_schema=object_schema(
                {"repo": {"type": "string", "description": "Repo id, name, path, or Git URL."}}
            ),
            handler=lambda args: handlers.communities_list(store, args),
        ),
        ToolSpec(
            name="codewiki_communities_name",
            description="Generate LLM names and summaries for graph communities.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "max_communities": {"type": "integer", "default": 40},
                }
            ),
            handler=lambda args: handlers.communities_name(store, args),
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
            name="codewiki_wiki_catalog_generate",
            description="Generate a wiki catalog for a repository and language.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "language": {"type": "string", "default": "en"},
                }
            ),
            handler=lambda args: handlers.wiki_catalog_generate(store, args),
        ),
        ToolSpec(
            name="codewiki_wiki_pages_generate",
            description="Generate all wiki pages for a repository and language.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "language": {"type": "string", "default": "en"},
                }
            ),
            handler=lambda args: handlers.wiki_pages_generate(store, args),
        ),
        ToolSpec(
            name="codewiki_wiki_pages_update",
            description="Incrementally update graph state, then generate missing or stale wiki pages.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "language": {"type": "string", "default": "en"},
                    "refresh_chunks": {"type": "boolean", "default": True},
                }
            ),
            handler=lambda args: handlers.wiki_pages_update(store, args),
        ),
        ToolSpec(
            name="codewiki_wiki_page_regenerate",
            description="Regenerate a single wiki page by slug and language.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "slug": {"type": "string", "description": "Wiki page slug."},
                    "language": {"type": "string", "default": "en"},
                },
                required=["slug"],
            ),
            handler=lambda args: handlers.wiki_page_regenerate(store, args),
        ),
        ToolSpec(
            name="codewiki_wiki_translate",
            description="Translate an existing wiki from one language to another.",
            input_schema=object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "source_language": {"type": "string", "default": "en"},
                    "target_language": {"type": "string", "description": "Target language code."},
                },
                required=["target_language"],
            ),
            handler=lambda args: handlers.wiki_translate(store, args),
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
