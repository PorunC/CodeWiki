from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend.app.database import get_store
from backend.app.services.async_tasks import repo_write_lock, run_blocking
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanResult, RepoScanner

router = APIRouter()


class CreateRepoRequest(BaseModel):
    path: str
    name: str | None = None
    source_type: str = "local"


class ScanRepoRequest(CreateRepoRequest):
    pass


@router.post("")
async def create_repo(payload: CreateRepoRequest) -> RepoDescriptor:
    scanner = RepoScanner()
    try:
        repo = await run_blocking(
            scanner.describe,
            payload.path,
            name=payload.name,
            source_type=payload.source_type,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with repo_write_lock(repo.id):
        return await run_blocking(get_store().upsert_repo, repo)


@router.post("/scan")
async def scan_repo(payload: ScanRepoRequest) -> RepoScanResult:
    scanner = RepoScanner()
    try:
        return await run_blocking(
            scanner.scan,
            payload.path,
            name=payload.name,
            source_type=payload.source_type,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_repos() -> list[dict[str, str]]:
    repos = await run_blocking(get_store().list_repos)
    return [
        {
            "id": repo.id,
            "name": repo.name,
            "path": repo.path,
            "source_type": repo.source_type,
            "git_url": repo.git_url or "",
            "commit_hash": repo.commit_hash or "",
        }
        for repo in repos
    ]


@router.get("/{repo_id}")
async def get_repo(repo_id: str) -> dict[str, str]:
    repo = await run_blocking(get_store().get_repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    return {
        "id": repo.id,
        "name": repo.name,
        "path": repo.path,
        "source_type": repo.source_type,
        "git_url": repo.git_url or "",
        "commit_hash": repo.commit_hash or "",
    }


@router.delete("/{repo_id}", status_code=204)
async def delete_repo(repo_id: str) -> Response:
    async with repo_write_lock(repo_id):
        deleted = await run_blocking(get_store().delete_repo, repo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    return Response(status_code=204)
