from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.database import SQLiteStore, get_store
from backend.app.services.analyzer import AnalysisService
from backend.app.services.community_namer import CommunityNamer
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.incremental_updater import IncrementalUpdater
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.wiki import WikiGenerator

router = APIRouter()


class AnalyzeRepoRequest(BaseModel):
    name_communities: bool = False


class IncrementalUpdateRequest(BaseModel):
    refresh_chunks: bool = True
    name_communities: bool = False
    regenerate_wiki: bool = True


@router.post("/{repo_id}/analyze")
async def analyze_repo(repo_id: str, payload: AnalyzeRepoRequest | None = None) -> dict[str, object]:
    store = get_store()
    if store.get_repo(repo_id) is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    request = payload or AnalyzeRepoRequest()
    try:
        result = AnalysisService(store=store).analyze(repo_id)
        naming_result = (
            await CommunityNamer(LLMGateway(get_settings()), store=store).name_communities(repo_id)
            if request.name_communities
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = {
        "run_id": result.run_id,
        "repo_id": result.repo_id,
        "status": result.status,
        "scanned_count": result.scanned_count,
        "parsed_file_count": result.parsed_file_count,
        "node_count": result.node_count,
        "edge_count": result.edge_count,
        "community_count": result.community_count,
        "errors": result.errors,
    }
    if naming_result is not None:
        response["community_naming"] = asdict(naming_result)
    return response


@router.post("/{repo_id}/update")
async def update_repo(
    repo_id: str,
    payload: IncrementalUpdateRequest | None = None,
) -> dict[str, object]:
    store = get_store()
    if store.get_repo(repo_id) is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    request = payload or IncrementalUpdateRequest()
    try:
        result = IncrementalUpdater(store=store).update(
            repo_id,
            refresh_chunks=request.refresh_chunks,
        )
        wiki_regeneration = (
            await _regenerate_stale_wiki_pages(repo_id, result.stale_pages, store=store)
            if request.regenerate_wiki
            else _skipped_wiki_regeneration(result.stale_pages)
        )
        naming_result = (
            await CommunityNamer(LLMGateway(get_settings()), store=store).name_communities(repo_id)
            if request.name_communities
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        "chunk_count": result.chunk_count,
        "stale_pages": result.stale_pages,
        "wiki_regeneration": wiki_regeneration,
        "errors": result.errors,
    }
    if naming_result is not None:
        response["community_naming"] = asdict(naming_result)
    return response


async def _regenerate_stale_wiki_pages(
    repo_id: str,
    stale_pages: list[str],
    *,
    store: SQLiteStore,
) -> dict[str, object]:
    if not stale_pages:
        return {"requested": True, "pages": [], "errors": []}

    settings = get_settings()
    generator = WikiGenerator(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
    )
    regenerated_pages: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for slug in stale_pages:
        try:
            result = await generator.regenerate_page(repo_id, slug)
        except Exception as exc:
            errors.append({"slug": slug, "error": str(exc)})
            continue
        regenerated_pages.append(
            {
                "slug": result.page.slug,
                "status": result.page.status,
                "validation_errors": result.validation_errors,
            }
        )
    return {"requested": True, "pages": regenerated_pages, "errors": errors}


def _skipped_wiki_regeneration(stale_pages: list[str]) -> dict[str, object]:
    return {
        "requested": False,
        "pages": [],
        "errors": [],
        "skipped_pages": stale_pages,
    }


@router.get("/{repo_id}/runs")
async def list_runs(repo_id: str) -> list[dict[str, object]]:
    return [
        {
            "id": run.id,
            "repo_id": run.repo_id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error": run.error,
            "stats": run.stats,
        }
        for run in get_store().list_analysis_runs(repo_id)
    ]


@router.get("/{repo_id}/runs/{run_id}")
async def get_run(repo_id: str, run_id: str) -> dict[str, object]:
    run = get_store().get_analysis_run(run_id)
    if run is None or run.repo_id != repo_id:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return {
        "id": run.id,
        "repo_id": run.repo_id,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "stats": run.stats,
    }
