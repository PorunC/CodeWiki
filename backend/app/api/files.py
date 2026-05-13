from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.database import get_store
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanner, ScannedFile

router = APIRouter()


@router.get("/{repo_id}/files")
async def list_repo_files(repo_id: str) -> dict[str, object]:
    store = get_store()
    repo = store.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")

    try:
        scan = RepoScanner().scan(repo.path, name=repo.name, source_type=repo.source_type)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "repo_id": repo.id,
        "root": _tree_payload(repo, scan.files),
        "files": [_file_payload(scanned_file) for scanned_file in scan.files],
        "scanned_count": scan.scanned_count,
        "ignored_count": scan.ignored_count,
        "skipped_count": scan.skipped_count,
    }


def _tree_payload(repo: RepoDescriptor, files: list[ScannedFile]) -> dict[str, Any]:
    root = _directory_node(repo.name, "")
    directory_by_path: dict[str, dict[str, Any]] = {"": root}

    for scanned_file in files:
        parent = root
        parts = [part for part in scanned_file.path.split("/") if part]
        current_path_parts: list[str] = []
        for directory_name in parts[:-1]:
            current_path_parts.append(directory_name)
            directory_path = "/".join(current_path_parts)
            directory = directory_by_path.get(directory_path)
            if directory is None:
                directory = _directory_node(directory_name, directory_path)
                directory_by_path[directory_path] = directory
                parent["children"].append(directory)
            parent = directory

        if parts:
            parent["children"].append(
                {
                    "type": "file",
                    "name": parts[-1],
                    "path": scanned_file.path,
                    "language": scanned_file.language,
                    "is_source": scanned_file.is_source,
                    "size_bytes": scanned_file.size_bytes,
                    "sha256": scanned_file.sha256,
                    "modified_at": scanned_file.modified_at,
                }
            )

    _sort_tree(root)
    return root


def _directory_node(name: str, path: str) -> dict[str, Any]:
    return {
        "type": "directory",
        "name": name,
        "path": path,
        "children": [],
    }


def _sort_tree(node: dict[str, Any]) -> None:
    children = node.get("children")
    if not isinstance(children, list):
        return
    children.sort(
        key=lambda item: (
            0 if item.get("type") == "directory" else 1,
            str(item.get("name", "")).lower(),
        )
    )
    for child in children:
        if child.get("type") == "directory":
            _sort_tree(child)


def _file_payload(scanned_file: ScannedFile) -> dict[str, object]:
    return {
        "path": scanned_file.path,
        "language": scanned_file.language,
        "is_source": scanned_file.is_source,
        "size_bytes": scanned_file.size_bytes,
        "sha256": scanned_file.sha256,
        "modified_at": scanned_file.modified_at,
    }
