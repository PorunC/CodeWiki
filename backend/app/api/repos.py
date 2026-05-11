from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.services.repo_scanner import RepoDescriptor, RepoScanner

router = APIRouter()


class CreateRepoRequest(BaseModel):
    path: str
    name: str | None = None
    source_type: str = "local"


@router.post("")
async def create_repo(payload: CreateRepoRequest) -> RepoDescriptor:
    scanner = RepoScanner()
    return scanner.describe(payload.path, name=payload.name, source_type=payload.source_type)


@router.get("")
async def list_repos() -> list[dict[str, str]]:
    return []


@router.get("/{repo_id}")
async def get_repo(repo_id: str) -> dict[str, str]:
    return {"id": repo_id, "status": "not_persisted_yet"}

