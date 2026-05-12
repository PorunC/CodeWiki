from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.database import get_store
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
        repo = scanner.describe(payload.path, name=payload.name, source_type=payload.source_type)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_store().upsert_repo(repo)


@router.post("/scan")
async def scan_repo(payload: ScanRepoRequest) -> RepoScanResult:
    scanner = RepoScanner()
    try:
        return scanner.scan(payload.path, name=payload.name, source_type=payload.source_type)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_repos() -> list[dict[str, str]]:
    return [
        {
            "id": repo.id,
            "name": repo.name,
            "path": repo.path,
            "source_type": repo.source_type,
            "git_url": repo.git_url or "",
            "commit_hash": repo.commit_hash or "",
        }
        for repo in get_store().list_repos()
    ]


@router.get("/{repo_id}")
async def get_repo(repo_id: str) -> dict[str, str]:
    repo = get_store().get_repo(repo_id)
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
