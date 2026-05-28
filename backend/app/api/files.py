from fastapi import APIRouter, HTTPException

from backend.app.database import get_store
from backend.app.services.async_tasks import run_blocking
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.repo_scanner.tree import file_payload, file_tree_payload

router = APIRouter()


@router.get("/{repo_id}/files")
async def list_repo_files(repo_id: str) -> dict[str, object]:
    store = get_store()
    repo = store.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")

    try:
        scan = await run_blocking(
            RepoScanner().scan_files,
            repo.path,
            name=repo.name,
            source_type=repo.source_type,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "repo_id": repo.id,
        "root": file_tree_payload(repo, scan.files),
        "files": [file_payload(scanned_file) for scanned_file in scan.files],
        "scanned_count": scan.scanned_count,
        "ignored_count": scan.ignored_count,
        "skipped_count": scan.skipped_count,
    }
