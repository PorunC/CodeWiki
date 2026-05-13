from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.database import get_store
from backend.app.services.analyzer import AnalysisService
from backend.app.services.community_namer import CommunityNamer
from backend.app.services.incremental_updater import IncrementalUpdater
from backend.app.services.llm_gateway import LLMGateway

router = APIRouter()


class AnalyzeRepoRequest(BaseModel):
    name_communities: bool = False


class IncrementalUpdateRequest(BaseModel):
    refresh_chunks: bool = True
    name_communities: bool = False


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
        "errors": result.errors,
    }
    if naming_result is not None:
        response["community_naming"] = asdict(naming_result)
    return response


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
