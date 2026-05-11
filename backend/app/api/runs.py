from fastapi import APIRouter

router = APIRouter()


@router.post("/{repo_id}/analyze")
async def analyze_repo(repo_id: str) -> dict[str, str]:
    return {"repo_id": repo_id, "status": "queued"}


@router.get("/{repo_id}/runs")
async def list_runs(repo_id: str) -> list[dict[str, str]]:
    return []


@router.get("/{repo_id}/runs/{run_id}")
async def get_run(repo_id: str, run_id: str) -> dict[str, str]:
    return {"repo_id": repo_id, "run_id": run_id, "status": "unknown"}

