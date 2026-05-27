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
from backend.app.services.analyzer import AnalysisService, _llm_configured
from backend.app.services.community.namer import CommunityNamer
from backend.app.services.community.naming import CommunityNamingResult
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.llm.gateway import LLMGateway
from backend.app.services.llm.model_router import ModelRouter
from backend.app.services.question_answerer import QuestionAnswerer
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.repo_scanner.tree import file_payload, file_tree_payload
from backend.app.services.wiki import WikiGenerator


async def repos_list(store: CodeWikiStore, _args: JsonObject) -> Any:
    return [repo_payload(repo) for repo in store.list_repos()]


async def repo_add(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = RepoScanner().describe(
        required_string(args, "path"),
        name=optional_string(args, "name"),
        source_type=optional_string(args, "source_type") or "local",
    )
    return repo_payload(store.upsert_repo(repo))


async def repo_delete(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = _resolve_existing_repo(store, required_string(args, "repo"))
    return {"repo_id": repo.id, "deleted": store.delete_repo(repo.id)}


async def repo_scan(_store: CodeWikiStore, args: JsonObject) -> Any:
    scan = RepoScanner().scan(
        required_string(args, "path"),
        name=optional_string(args, "name"),
        source_type=optional_string(args, "source_type") or "local",
    )
    return jsonable(scan)


async def health(_store: CodeWikiStore, _args: JsonObject) -> Any:
    return {"status": "ok"}


async def llm_models(_store: CodeWikiStore, _args: JsonObject) -> Any:
    settings = get_settings()
    model_router = ModelRouter(settings)
    task_types = (
        "catalog",
        "community_summary",
        "cluster",
        "page",
        "translation",
        "qa",
        "embedding",
    )
    return {
        "mode": settings.llm.mode,
        "default_profile": _profile_payload(model_router.default_profile()),
        "profiles": {
            task_type: _profile_payload(model_router.profile_for(task_type))
            for task_type in task_types
        },
    }


async def analyze(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    analysis = await AnalysisService(store=store).analyze_with_community_summaries(
        repo.id,
        name_communities=bool_arg(args, "community_summaries", True),
    )
    return {
        "analysis": jsonable(analysis.analysis),
        "community_naming": jsonable(analysis.community_naming),
    }


async def incremental_update(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    updater = IncrementalUpdater(store=store)
    result, wiki_regeneration = await updater.update_with_wiki_regeneration(
        repo.id,
        refresh_chunks=bool_arg(args, "refresh_chunks", True),
        regenerate_wiki=bool_arg(args, "regenerate_wiki", True),
    )
    response = {
        "run_id": result.run_id,
        "repo_id": result.repo_id,
        "status": result.status,
        "plan": result.plan.as_dict(),
        "scanned_count": result.scanned_count,
        "parsed_file_count": result.parsed_file_count,
        "reused_file_count": result.reused_file_count,
        "node_count": result.node_count,
        "edge_count": result.edge_count,
        "community_count": result.community_count,
        "community_count_by_level": result.community_count_by_level,
        "chunk_count": result.chunk_count,
        "stale_pages": result.stale_pages,
        "wiki_regeneration": wiki_regeneration,
        "errors": result.errors,
    }
    if bool_arg(args, "community_summaries", True):
        response["community_naming"] = jsonable(await _name_communities(store, repo.id))
    return response


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


async def files_tree(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    scan = RepoScanner().scan(repo.path, name=repo.name, source_type=repo.source_type)
    return {
        "repo_id": repo.id,
        "root": file_tree_payload(repo, scan.files),
        "files": [file_payload(scanned_file) for scanned_file in scan.files],
        "scanned_count": scan.scanned_count,
        "ignored_count": scan.ignored_count,
        "skipped_count": scan.skipped_count,
    }


async def graph_dump(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    nodes, edges = store.get_graph(repo.id)
    return {
        "repo_id": repo.id,
        "nodes": nodes,
        "edges": edges,
        "communities": store.list_graph_communities(repo.id),
        "community_edges": store.list_graph_community_edges(repo.id),
    }


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


async def graph_callers(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    relationships = GraphQueryService(store=store).callers(
        repo.id,
        required_string(args, "symbol"),
        limit=int_arg(args, "limit", 20),
    )
    return jsonable(relationships)


async def graph_callees(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    relationships = GraphQueryService(store=store).callees(
        repo.id,
        required_string(args, "symbol"),
        limit=int_arg(args, "limit", 20),
    )
    return jsonable(relationships)


async def graph_impact(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    return jsonable(
        GraphQueryService(store=store).impact(
            repo.id,
            required_string(args, "symbol"),
            depth=int_arg(args, "depth", 2),
        )
    )


async def graph_explore(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = GraphQueryService(store=store).explore(
        repo.id,
        required_string(args, "query"),
        max_files=int_arg(args, "max_files", 12),
        max_nodes=int_arg(args, "max_nodes", 160),
    )
    return _with_pending_sync(store, repo.id, jsonable(result))


async def graph_context(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = GraphQueryService(store=store).explore(
        repo.id,
        required_string(args, "task"),
        max_files=int_arg(args, "max_files", 12),
        max_nodes=int_arg(args, "max_nodes", 160),
    )
    return _with_pending_sync(store, repo.id, jsonable(result))


async def graph_trace(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = GraphQueryService(store=store).trace(
        repo.id,
        required_string(args, "from_symbol"),
        required_string(args, "to_symbol"),
        max_depth=int_arg(args, "max_depth", 8),
    )
    return _with_pending_sync(store, repo.id, jsonable(result))


async def graph_node_context(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = GraphQueryService(store=store).node_context(
        repo.id,
        required_string(args, "symbol"),
        include_code=bool_arg(args, "include_code", True),
    )
    return _with_pending_sync(store, repo.id, jsonable(result))


async def graph_status(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    nodes, edges = store.get_graph(repo.id)
    nodes_by_type: dict[str, int] = {}
    edges_by_type: dict[str, int] = {}
    languages: dict[str, int] = {}
    for node in nodes:
        nodes_by_type[node.type] = nodes_by_type.get(node.type, 0) + 1
        if node.language:
            languages[node.language] = languages.get(node.language, 0) + 1
    for edge in edges:
        edges_by_type[edge.type] = edges_by_type.get(edge.type, 0) + 1
    payload = {
        "repo_id": repo.id,
        "file_count": sum(1 for node in nodes if node.type in {"file", "config"}),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "chunk_count": len(store.list_code_chunks(repo.id)),
        "nodes_by_type": dict(sorted(nodes_by_type.items())),
        "edges_by_type": dict(sorted(edges_by_type.items())),
        "languages": dict(sorted(languages.items())),
    }
    return _with_pending_sync(store, repo.id, payload, prefix_text=False)


async def graph_node_read(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    node_id = required_string(args, "node_id")
    nodes, edges = store.get_graph(repo.id)
    node = next((item for item in nodes if item.id == node_id), None)
    if node is None:
        raise ValueError(f"Node not found: {node_id}")
    adjacent_edges = [
        edge for edge in edges if edge.source_id == node_id or edge.target_id == node_id
    ]
    return {"node": node, "adjacent_edges": adjacent_edges}


async def communities_list(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    return jsonable(store.list_graph_communities(repo.id))


async def communities_name(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = await CommunityNamer(LLMGateway(get_settings()), store=store).summarize_communities(
        repo.id,
        max_communities=int_arg(args, "max_communities", 40),
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


def _with_pending_sync(
    store: CodeWikiStore,
    repo_id: str,
    payload: Any,
    *,
    prefix_text: bool = True,
) -> Any:
    if not isinstance(payload, dict):
        return payload
    plan = IncrementalUpdater(store=store).plan(repo_id)
    pending_files = plan.affected_files
    payload["pending_sync"] = bool(pending_files)
    payload["pending_files"] = pending_files
    if pending_files and prefix_text and isinstance(payload.get("text"), str):
        shown = ", ".join(pending_files[:12])
        suffix = "" if len(pending_files) <= 12 else f", ... (+{len(pending_files) - 12} more)"
        payload["text"] = (
            "WARNING: index has pending file changes. Run codewiki_update or "
            f"`codewiki lite sync` before relying on this context. Pending: {shown}{suffix}\n\n"
            f"{payload['text']}"
        )
    return payload


async def wiki_catalog_generate(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    catalog = await _wiki_generator(store).generate_catalog(
        repo.id,
        language_code=optional_string(args, "language") or "en",
    )
    return jsonable(catalog)


async def wiki_pages_generate(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    results = await _wiki_generator(store).generate_all_pages(
        repo.id,
        language_code=optional_string(args, "language") or "en",
    )
    return [_page_result_payload(result) for result in results]


async def wiki_pages_update(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    incremental_result = IncrementalUpdater(store=store).update(
        repo.id,
        refresh_chunks=bool_arg(args, "refresh_chunks", True),
    )
    update = await _wiki_generator(store).update_pages(
        repo.id,
        language_code=optional_string(args, "language") or "en",
    )
    return {
        "repo_id": repo.id,
        "language_code": update.language_code,
        "generated_pages": update.generated_slugs,
        "reused_count": len(update.reused_pages),
        "stale_pages": update.stale_slugs,
        "missing_pages": update.missing_slugs,
        "deleted_page_count": update.deleted_page_count,
        "pages": [_page_result_payload(result) for result in update.results],
        "incremental_update": jsonable(incremental_result),
    }


async def wiki_page_regenerate(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = await _wiki_generator(store).regenerate_page(
        repo.id,
        required_string(args, "slug"),
        language_code=optional_string(args, "language") or "en",
    )
    return _page_result_payload(result)


async def wiki_translate(store: CodeWikiStore, args: JsonObject) -> Any:
    repo = resolve_repo(store, optional_string(args, "repo"))
    result = await _wiki_generator(store).translate_wiki(
        repo.id,
        source_language=optional_string(args, "source_language") or "en",
        target_language=required_string(args, "target_language"),
    )
    return {
        "repo_id": repo.id,
        "source_language": result.source_language,
        "target_language": result.target_language,
        "catalog": result.catalog,
        "page_count": len(result.pages),
        "pages": result.pages,
    }


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


def _wiki_generator(store: CodeWikiStore) -> WikiGenerator:
    settings = get_settings()
    return WikiGenerator(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
        settings=settings,
    )


def _page_result_payload(result: Any) -> dict[str, object]:
    return {
        "page": jsonable(result.page),
        "validation_errors": result.validation_errors,
    }


def _profile_payload(profile: Any) -> dict[str, object]:
    return {
        "model": profile.model,
        "provider_type": profile.provider_type or "",
        "endpoint": profile.endpoint or "",
        "has_api_key": bool(profile.api_key),
        "stream": profile.stream,
        "max_tokens": profile.max_tokens,
    }


async def _name_communities(store: CodeWikiStore, repo_id: str) -> CommunityNamingResult:
    settings = get_settings()
    if not _llm_configured(settings):
        return CommunityNamingResult(
            repo_id=repo_id,
            status="skipped",
            renamed_count=0,
            community_count=len(store.list_graph_communities(repo_id)),
            errors=["LLM community naming skipped because no LLM endpoint or API key is configured."],
        )
    try:
        return await CommunityNamer(LLMGateway(settings), store=store).summarize_communities(repo_id)
    except Exception as exc:
        return CommunityNamingResult(
            repo_id=repo_id,
            status="failed",
            renamed_count=0,
            community_count=len(store.list_graph_communities(repo_id)),
            errors=[str(exc)],
        )


def _resolve_existing_repo(store: CodeWikiStore, selector: str) -> Any:
    if repo := store.get_repo(selector):
        return repo
    repos = store.list_repos()
    name_matches = [repo for repo in repos if repo.name == selector]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        raise ValueError(f"Repository name is ambiguous: {selector}")
    prefix_matches = [repo for repo in repos if repo.id.startswith(selector)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        raise ValueError(f"Repository id prefix is ambiguous: {selector}")
    raise ValueError(f"Repository not found: {selector}")
