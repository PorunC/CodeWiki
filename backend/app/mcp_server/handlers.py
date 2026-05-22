from __future__ import annotations

from typing import Any

from backend.app.config import get_settings
from backend.app.database import CodeWikiStore
from backend.app.mcp_server.args import (
    bool_arg,
    int_arg,
    optional_list,
    optional_string,
    required_string,
    string_list_arg,
)
from backend.app.mcp_server.types import JsonObject
from backend.app.mcp_server.utils import jsonable, repo_payload, resolve_repo
from backend.app.schemas.ask import AskRequest
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.question_answerer import QuestionAnswerer
from backend.app.services.repo_scanner import RepoScanner


async def repos_list(store: CodeWikiStore, _args: JsonObject) -> Any:
    return [repo_payload(repo) for repo in store.list_repos()]


async def repo_add(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = RepoScanner().describe(
        required_string(args, "path"),
        name=optional_string(args, "name"),
        source_type=optional_string(args, "source_type") or "local",
    )
    return repo_payload(store.upsert_repo(repo))


async def analyze(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    analysis = await AnalysisService(store=store).analyze_with_community_summaries(
        repo.id,
        name_communities=bool_arg(args, "community_summaries", False),
    )
    return {
        "analysis": jsonable(analysis.analysis),
        "community_naming": jsonable(analysis.community_naming),
    }


async def graphrag_build(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = await GraphRAGRetriever(store=store).build_index(
        repo.id,
        include_embeddings=bool_arg(args, "embeddings", False),
    )
    return jsonable(result)


async def retrieve_context(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    trace = await GraphRAGRetriever(store=store).retrieve(
        repo.id,
        required_string(args, "query"),
        max_hops=int_arg(args, "max_hops", 2),
        include_embeddings=bool_arg(args, "include_embeddings", False),
    )
    return jsonable(trace)


async def ask(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    settings = get_settings()
    answer = await QuestionAnswerer(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
    ).answer(
        repo.id,
        AskRequest(
            question=required_string(args, "question"),
            max_hops=int_arg(args, "max_hops", 2),
        ),
    )
    return jsonable(answer)


async def graph_search(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    hits = GraphQueryService(store=store).search(
        repo.id,
        optional_string(args, "query") or "",
        types=optional_list(args, "type"),
        languages=optional_list(args, "language"),
        path_filters=optional_list(args, "path"),
        name_filters=optional_list(args, "name"),
        limit=int_arg(args, "limit", 20),
    )
    return jsonable(hits)


async def graph_explore(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = GraphQueryService(store=store).explore(
        repo.id,
        required_string(args, "query"),
        max_files=int_arg(args, "max_files", 12),
        max_nodes=int_arg(args, "max_nodes", 160),
    )
    return jsonable(result)


async def graph_affected(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = GraphQueryService(store=store).affected(
        repo.id,
        string_list_arg(args, "file_paths"),
        depth=int_arg(args, "depth", 5),
        test_glob=optional_string(args, "test_glob"),
    )
    return jsonable(result)


async def wiki_pages_list(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    pages = store.list_doc_pages(repo.id, language_code=optional_string(args, "language") or "en")
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


async def wiki_page_read(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    slug = required_string(args, "slug")
    page = store.get_doc_page(
        repo.id,
        slug,
        language_code=optional_string(args, "language") or "en",
    )
    if page is None:
        raise ValueError(f"Wiki page not found: {slug}")
    return jsonable(page)
