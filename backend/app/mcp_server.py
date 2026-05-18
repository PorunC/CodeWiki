from __future__ import annotations

import asyncio
import importlib.metadata
import json
import sys
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.database import SQLiteStore, get_store
from backend.app.schemas.ask import AskRequest
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.question_answerer import QuestionAnswerer
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanner, is_git_url

JsonObject = dict[str, Any]
ToolHandler = Callable[[JsonObject], Awaitable[Any]]

DEFAULT_PROTOCOL_VERSION = "2024-11-05"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: JsonObject
    handler: ToolHandler

    def payload(self) -> JsonObject:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class CodeWikiMCPServer:
    """Small stdio MCP server exposing CodeWiki workflows as tools."""

    def __init__(self, *, store: SQLiteStore | None = None) -> None:
        self.store = store or get_store()
        self.tools = _build_tools(self.store)

    async def handle_message(self, message: JsonObject) -> JsonObject | None:
        method = message.get("method")
        request_id = message.get("id")
        is_notification = "id" not in message
        try:
            if method == "initialize":
                return _result(request_id, self._initialize_result(message.get("params")))
            if method in {"notifications/initialized", "initialized"}:
                return None
            if isinstance(method, str) and method.startswith("notifications/"):
                return None
            if method == "ping":
                return _result(request_id, {})
            if method == "tools/list":
                return _result(request_id, {"tools": [tool.payload() for tool in self.tools.values()]})
            if method == "tools/call":
                return _result(request_id, await self._call_tool(_params(message)))
            if method == "resources/list":
                return _result(request_id, {"resources": []})
            if method == "prompts/list":
                return _result(request_id, {"prompts": []})
            if method == "logging/setLevel":
                return _result(request_id, {})
            if method in {"shutdown", "exit"}:
                return None if is_notification else _result(request_id, {})
        except Exception as exc:
            if is_notification:
                return None
            return _error(request_id, -32603, str(exc))
        if is_notification:
            return None
        return _error(request_id, -32601, f"Method not found: {method}")

    def _initialize_result(self, params: object) -> JsonObject:
        protocol_version = DEFAULT_PROTOCOL_VERSION
        if isinstance(params, dict) and isinstance(params.get("protocolVersion"), str):
            protocol_version = params["protocolVersion"]
        return {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "codewiki",
                "version": _package_version(),
            },
        }

    async def _call_tool(self, params: JsonObject) -> JsonObject:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("tools/call requires a tool name.")
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object.")
        try:
            payload = await tool.handler(arguments)
        except Exception as exc:
            return _tool_response({"error": str(exc)}, is_error=True)
        return _tool_response(payload)


async def run_stdio(server: CodeWikiMCPServer | None = None) -> None:
    server = server or CodeWikiMCPServer()
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                response = _error(None, -32600, "Invalid JSON-RPC request.")
            else:
                response = await server.handle_message(message)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"Parse error: {exc}")
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def main() -> None:
    asyncio.run(run_stdio())


def _build_tools(store: SQLiteStore) -> dict[str, ToolSpec]:
    tools = [
        ToolSpec(
            name="codewiki_repos_list",
            description="List repositories registered in the local CodeWiki database.",
            input_schema=_object_schema({}),
            handler=lambda args: _repos_list(store, args),
        ),
        ToolSpec(
            name="codewiki_repo_add",
            description="Register a local repository path or Git URL in CodeWiki.",
            input_schema=_object_schema(
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
            handler=lambda args: _repo_add(store, args),
        ),
        ToolSpec(
            name="codewiki_analyze",
            description="Run AST graph analysis for a registered repo, path, name, or id.",
            input_schema=_object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "community_summaries": {
                        "type": "boolean",
                        "description": "Whether to generate LLM community summaries.",
                        "default": False,
                    },
                }
            ),
            handler=lambda args: _analyze(store, args),
        ),
        ToolSpec(
            name="codewiki_graphrag_build",
            description="Build GraphRAG source chunks and optional embeddings for a repository.",
            input_schema=_object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "embeddings": {
                        "type": "boolean",
                        "description": "Whether to build vector embeddings.",
                        "default": False,
                    },
                }
            ),
            handler=lambda args: _graphrag_build(store, args),
        ),
        ToolSpec(
            name="codewiki_retrieve_context",
            description="Retrieve GraphRAG context for a repository question without calling an LLM.",
            input_schema=_object_schema(
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
            handler=lambda args: _retrieve_context(store, args),
        ),
        ToolSpec(
            name="codewiki_ask",
            description="Ask a GraphRAG-grounded question using the configured LLM provider.",
            input_schema=_object_schema(
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
            handler=lambda args: _ask(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_search",
            description="Search indexed code graph symbols by name, path, signature, or docstring.",
            input_schema=_object_schema(
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
            handler=lambda args: _graph_search(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_explore",
            description="Build source-section exploration context for a query.",
            input_schema=_object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "query": {"type": "string", "description": "Exploration query."},
                    "max_files": {"type": "integer", "default": 12},
                    "max_nodes": {"type": "integer", "default": 160},
                },
                required=["query"],
            ),
            handler=lambda args: _graph_explore(store, args),
        ),
        ToolSpec(
            name="codewiki_graph_affected",
            description="Find files, tests, and wiki pages affected by changed files.",
            input_schema=_object_schema(
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
            handler=lambda args: _graph_affected(store, args),
        ),
        ToolSpec(
            name="codewiki_wiki_pages_list",
            description="List generated wiki pages for a repository.",
            input_schema=_object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "language": {"type": "string", "default": "en"},
                }
            ),
            handler=lambda args: _wiki_pages_list(store, args),
        ),
        ToolSpec(
            name="codewiki_wiki_page_read",
            description="Read a generated wiki page by slug.",
            input_schema=_object_schema(
                {
                    "repo": {"type": "string", "description": "Repo id, name, path, or Git URL."},
                    "slug": {"type": "string", "description": "Wiki page slug."},
                    "language": {"type": "string", "default": "en"},
                },
                required=["slug"],
            ),
            handler=lambda args: _wiki_page_read(store, args),
        ),
    ]
    return {tool.name: tool for tool in tools}


async def _repos_list(store: SQLiteStore, _args: JsonObject) -> Any:
    return [_repo_payload(repo) for repo in store.list_repos()]


async def _repo_add(store: SQLiteStore, args: JsonObject) -> Any:
    repo = RepoScanner().describe(
        _required_string(args, "path"),
        name=_optional_string(args, "name"),
        source_type=_optional_string(args, "source_type") or "local",
    )
    return _repo_payload(store.upsert_repo(repo))


async def _analyze(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    analysis = await AnalysisService(store=store).analyze_with_community_summaries(
        repo.id,
        name_communities=_bool_arg(args, "community_summaries", False),
    )
    payload = {
        "analysis": _jsonable(analysis.analysis),
        "community_naming": _jsonable(analysis.community_naming),
    }
    return payload


async def _graphrag_build(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    result = await GraphRAGRetriever(store=store).build_index(
        repo.id,
        include_embeddings=_bool_arg(args, "embeddings", False),
    )
    return _jsonable(result)


async def _retrieve_context(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    trace = await GraphRAGRetriever(store=store).retrieve(
        repo.id,
        _required_string(args, "query"),
        max_hops=_int_arg(args, "max_hops", 2),
        include_embeddings=_bool_arg(args, "include_embeddings", False),
    )
    return _jsonable(trace)


async def _ask(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    settings = get_settings()
    answer = await QuestionAnswerer(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
    ).answer(
        repo.id,
        AskRequest(
            question=_required_string(args, "question"),
            max_hops=_int_arg(args, "max_hops", 2),
        ),
    )
    return _jsonable(answer)


async def _graph_search(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    hits = GraphQueryService(store=store).search(
        repo.id,
        _optional_string(args, "query") or "",
        types=_optional_list(args, "type"),
        languages=_optional_list(args, "language"),
        path_filters=_optional_list(args, "path"),
        name_filters=_optional_list(args, "name"),
        limit=_int_arg(args, "limit", 20),
    )
    return _jsonable(hits)


async def _graph_explore(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    result = GraphQueryService(store=store).explore(
        repo.id,
        _required_string(args, "query"),
        max_files=_int_arg(args, "max_files", 12),
        max_nodes=_int_arg(args, "max_nodes", 160),
    )
    return _jsonable(result)


async def _graph_affected(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    result = GraphQueryService(store=store).affected(
        repo.id,
        _string_list_arg(args, "file_paths"),
        depth=_int_arg(args, "depth", 5),
        test_glob=_optional_string(args, "test_glob"),
    )
    return _jsonable(result)


async def _wiki_pages_list(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    pages = store.list_doc_pages(repo.id, language_code=_optional_string(args, "language") or "en")
    return [
        {
            "slug": page.slug,
            "title": page.title,
            "parent_slug": page.parent_slug,
            "language_code": page.language_code,
            "status": page.status,
            "updated_at": page.updated_at,
            "source_ref_count": len(page.source_refs),
            "graph_ref_count": len(page.graph_refs),
        }
        for page in pages
    ]


async def _wiki_page_read(store: SQLiteStore, args: JsonObject) -> Any:
    repo = _resolve_repo(store, _optional_string(args, "repo"))
    page = store.get_doc_page(
        repo.id,
        _required_string(args, "slug"),
        language_code=_optional_string(args, "language") or "en",
    )
    if page is None:
        raise ValueError(f"Wiki page not found: {args['slug']}")
    return _jsonable(page)


def _resolve_repo(store: SQLiteStore, selector: str | None) -> RepoDescriptor:
    selector = (selector or ".").strip() or "."
    if repo := store.get_repo(selector):
        return repo

    repos = store.list_repos()
    exact_name_matches = [repo for repo in repos if repo.name == selector]
    if len(exact_name_matches) == 1:
        return exact_name_matches[0]
    if len(exact_name_matches) > 1:
        raise ValueError(f"Repository name is ambiguous: {selector}")

    prefix_matches = [repo for repo in repos if repo.id.startswith(selector)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        raise ValueError(f"Repository id prefix is ambiguous: {selector}")

    path = Path(selector).expanduser()
    if path.exists() and path.is_dir():
        resolved_path = path.resolve()
        for repo in repos:
            if Path(repo.path).expanduser().resolve() == resolved_path:
                return repo
        return store.upsert_repo(RepoScanner().describe(str(resolved_path)))

    if is_git_url(selector):
        return store.upsert_repo(RepoScanner().describe(selector))

    raise ValueError(
        f"Repository not found: {selector}. Use a repo id, id prefix, name, path, Git URL, "
        "or run from inside a repository directory."
    )


def _repo_payload(repo: RepoDescriptor) -> JsonObject:
    return _jsonable(repo)


def _object_schema(properties: JsonObject, *, required: list[str] | None = None) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _params(message: JsonObject) -> JsonObject:
    params = message.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("JSON-RPC params must be an object.")
    return params


def _tool_response(payload: Any, *, is_error: bool = False) -> JsonObject:
    text = payload if isinstance(payload, str) else json.dumps(_jsonable(payload), indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _result(request_id: Any, result: Any) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _required_string(args: JsonObject, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Argument '{key}' must be a non-empty string.")
    return value.strip()


def _optional_string(args: JsonObject, key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Argument '{key}' must be a string.")
    return value.strip() or None


def _int_arg(args: JsonObject, key: str, default: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Argument '{key}' must be an integer.")
    return value


def _bool_arg(args: JsonObject, key: str, default: bool) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"Argument '{key}' must be a boolean.")
    return value


def _optional_list(args: JsonObject, key: str) -> list[str] | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError(f"Argument '{key}' must be a string or list of strings.")


def _string_list_arg(args: JsonObject, key: str) -> list[str]:
    value = args.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Argument '{key}' must be a list of strings.")
    return value


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _package_version() -> str:
    try:
        return importlib.metadata.version("codewiki")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


if __name__ == "__main__":
    main()
