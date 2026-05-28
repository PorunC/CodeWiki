from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.database import get_store
from backend.app.services.analyzer import AnalysisService, _llm_configured
from backend.app.services.async_tasks import repo_write_lock
from backend.app.services.community.namer import CommunityNamer
from backend.app.services.community.naming import CommunityNamingResult
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.llm.gateway import LLMGateway

router = APIRouter()


class AnalyzeRepoRequest(BaseModel):
    name_communities: bool = True


class IncrementalUpdateRequest(BaseModel):
    refresh_chunks: bool = True
    name_communities: bool = True
    regenerate_wiki: bool = True


@router.post("/{repo_id}/analyze")
async def analyze_repo(
    repo_id: str,
    background_tasks: BackgroundTasks,
    payload: AnalyzeRepoRequest | None = None,
) -> dict[str, object]:
    store = get_store()
    request = payload or AnalyzeRepoRequest()
    if store.get_repo(repo_id) is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    active_run = _active_analysis_run(repo_id)
    if active_run is not None:
        return _run_response(active_run)

    run = store.create_analysis_run(repo_id)
    store.update_analysis_run_stats(
        run.id,
        {
            "mode": "queued",
            "progress": {
                "stage": "queued",
                "label": "Queued",
                "message": "Analysis queued.",
            },
        },
    )
    background_tasks.add_task(
        _analyze_background,
        repo_id,
        run.id,
        request.name_communities,
    )
    return _run_response(store.get_analysis_run(run.id) or run)


async def _analyze_background(repo_id: str, run_id: str, name_communities: bool) -> None:
    store = get_store()
    async with repo_write_lock(repo_id):
        progress = AnalysisRunProgress(store, run_id)
        try:
            analysis = await AnalysisService(store=store).analyze_with_community_summaries(
                repo_id,
                name_communities=False,
                run_id=run_id,
                progress_callback=progress.update,
            )
            result = analysis.analysis
            naming_result = _queued_or_skipped_community_naming(repo_id) if name_communities else None
            stats = {
                **result.stats(),
                "progress": {
                    "stage": "done",
                    "label": "Done",
                    "message": (
                        f"Analysis complete: {result.node_count} nodes, "
                        f"{result.edge_count} edges, {result.community_count} communities."
                    ),
                },
            }
            if naming_result is not None:
                stats["community_naming"] = asdict(naming_result)
            store.update_analysis_run_stats(run_id, stats)
        except Exception as exc:
            current = store.get_analysis_run(run_id)
            stats = dict(current.stats) if current is not None else {}
            stats["progress"] = {
                "stage": "failed",
                "label": "Failed",
                "message": str(exc),
            }
            try:
                store.finish_analysis_run(run_id, status="failed", stats=stats, error=str(exc))
            except ValueError:
                pass
            return

    if name_communities:
        naming_result = _queued_or_skipped_community_naming(repo_id)
        if naming_result.status == "queued":
            await _name_communities_background(repo_id)


class AnalysisRunProgress:
    def __init__(self, store, run_id: str) -> None:
        self.store = store
        self.run_id = run_id
        self.latest: dict[str, object] = {}

    def update(self, stage: str, payload: dict[str, object]) -> None:
        self.latest = {
            **self.latest,
            "progress": {
                "stage": stage,
                "label": _analysis_stage_label(stage),
                "message": _analysis_stage_message(stage, payload),
                **payload,
            },
        }
        self.store.update_analysis_run_stats(self.run_id, self.latest)


def _active_analysis_run(repo_id: str):
    for run in get_store().list_analysis_runs(repo_id):
        if run.status == "running":
            return run
    return None


def _run_response(run) -> dict[str, object]:
    stats = run.stats or {}
    response = {
        "run_id": run.id,
        "id": run.id,
        "repo_id": run.repo_id,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "stats": stats,
        "mode": stats.get("mode", ""),
        "scanned_count": stats.get("scanned_count", 0),
        "parsed_file_count": stats.get("parsed_file_count", 0),
        "reused_file_count": stats.get("reused_file_count", 0),
        "node_count": stats.get("node_count", 0),
        "edge_count": stats.get("edge_count", 0),
        "chunk_count": len(get_store().list_code_chunks(run.repo_id)) if run.status == "done" else 0,
        "community_count": stats.get("community_count", 0),
        "community_count_by_level": stats.get("community_count_by_level", {}),
        "errors": stats.get("errors", []),
    }
    if "community_naming" in stats:
        response["community_naming"] = stats["community_naming"]
    return response


def _analysis_stage_label(stage: str) -> str:
    return {
        "scan_start": "Scanning",
        "scan_done": "Scan complete",
        "plan_done": "Planning",
        "parse_start": "Parsing",
        "parse_progress": "Parsing",
        "parse_done": "Parse complete",
        "graph_start": "Building graph",
        "graph_done": "Graph built",
        "communities_start": "Detecting communities",
        "communities_done": "Communities detected",
        "persist_start": "Saving graph",
        "persist_done": "Graph saved",
        "analysis_done": "Done",
    }.get(stage, stage.replace("_", " ").title())


def _analysis_stage_message(stage: str, payload: dict[str, object]) -> str:
    if stage == "scan_start":
        return f"Scanning {payload.get('repo', 'repository')}..."
    if stage == "scan_done":
        return (
            f"Scanned {payload.get('scanned', 0)} files "
            f"({payload.get('skipped', 0)} skipped)."
        )
    if stage == "plan_done":
        return (
            f"Planned changes: {payload.get('changed', 0)} changed, "
            f"{payload.get('new', 0)} new, {payload.get('deleted', 0)} deleted."
        )
    if stage == "parse_start":
        return f"Parsing {payload.get('total', 0)} source files..."
    if stage == "parse_progress":
        completed = _int_payload(payload, "completed")
        total = _int_payload(payload, "total")
        path = str(payload.get("path") or "")
        suffix = f" ({path})" if path else ""
        return f"Parsing {completed} / {total}{suffix}"
    if stage == "parse_done":
        return (
            f"Parsed {payload.get('parsed_files', 0)} files, "
            f"{payload.get('symbols', 0)} symbols."
        )
    if stage == "graph_start":
        return f"Building graph from {payload.get('symbols', 0)} symbols..."
    if stage == "graph_done":
        return f"Built {payload.get('nodes', 0)} nodes and {payload.get('edges', 0)} edges."
    if stage == "communities_start":
        return "Detecting graph communities..."
    if stage == "communities_done":
        return f"Detected {payload.get('communities', 0)} communities."
    if stage == "persist_start":
        return (
            f"Saving {payload.get('nodes', 0)} nodes, "
            f"{payload.get('edges', 0)} edges, and {payload.get('communities', 0)} communities..."
        )
    if stage == "persist_done":
        return "Graph saved."
    if stage == "analysis_done":
        return "Analysis complete."
    return _analysis_stage_label(stage)


def _int_payload(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    return value if isinstance(value, int) else 0


@router.post("/{repo_id}/update")
async def update_repo(
    repo_id: str,
    background_tasks: BackgroundTasks,
    payload: IncrementalUpdateRequest | None = None,
) -> dict[str, object]:
    store = get_store()
    request = payload or IncrementalUpdateRequest()
    try:
        async with repo_write_lock(repo_id):
            if store.get_repo(repo_id) is None:
                raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
            updater = IncrementalUpdater(store=store)
            result, wiki_regeneration = await updater.update_with_wiki_regeneration(
                repo_id,
                refresh_chunks=request.refresh_chunks,
                regenerate_wiki=request.regenerate_wiki,
            )
            naming_result = _queued_or_skipped_community_naming(repo_id) if request.name_communities else None
            if naming_result is not None and naming_result.status == "queued":
                background_tasks.add_task(_name_communities_background, repo_id)
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
        "community_count_by_level": result.community_count_by_level,
        "chunk_count": result.chunk_count,
        "stale_pages": result.stale_pages,
        "wiki_regeneration": wiki_regeneration,
        "errors": result.errors,
    }
    if naming_result is not None:
        response["community_naming"] = asdict(naming_result)
    return response


def _queued_or_skipped_community_naming(repo_id: str) -> CommunityNamingResult:
    settings = get_settings()
    community_count = len(get_store().list_graph_communities(repo_id))
    if not _llm_configured(settings):
        return CommunityNamingResult(
            repo_id=repo_id,
            status="skipped",
            renamed_count=0,
            community_count=community_count,
            errors=["LLM community naming skipped because no LLM endpoint or API key is configured."],
        )
    return CommunityNamingResult(
        repo_id=repo_id,
        status="queued",
        renamed_count=0,
        community_count=community_count,
        errors=[],
    )


async def _name_communities_background(repo_id: str) -> None:
    async with repo_write_lock(repo_id):
        await _name_communities(repo_id)


async def _name_communities(repo_id: str) -> CommunityNamingResult:
    settings = get_settings()
    if not _llm_configured(settings):
        return CommunityNamingResult(
            repo_id=repo_id,
            status="skipped",
            renamed_count=0,
            community_count=len(get_store().list_graph_communities(repo_id)),
            errors=["LLM community naming skipped because no LLM endpoint or API key is configured."],
        )
    try:
        return await CommunityNamer(LLMGateway(settings), store=get_store()).summarize_communities(repo_id)
    except Exception as exc:
        return CommunityNamingResult(
            repo_id=repo_id,
            status="failed",
            renamed_count=0,
            community_count=len(get_store().list_graph_communities(repo_id)),
            errors=[str(exc)],
        )


@router.get("/{repo_id}/runs")
async def list_runs(repo_id: str) -> list[dict[str, object]]:
    return [_run_response(run) for run in get_store().list_analysis_runs(repo_id)]


@router.get("/{repo_id}/runs/{run_id}")
async def get_run(repo_id: str, run_id: str) -> dict[str, object]:
    run = get_store().get_analysis_run(run_id)
    if run is None or run.repo_id != repo_id:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return _run_response(run)
