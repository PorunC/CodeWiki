from typing import Any

from backend.app.services.repo_scanner.models import RepoDescriptor, RepoFile


def file_tree_payload(repo: RepoDescriptor, files: list[RepoFile]) -> dict[str, Any]:
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
            parent["children"].append(_file_tree_node(scanned_file))

    _sort_tree(root)
    return root


def file_payload(scanned_file: RepoFile) -> dict[str, object]:
    payload = {
        "path": scanned_file.path,
        "language": scanned_file.language,
        "is_source": scanned_file.is_source,
        "size_bytes": scanned_file.size_bytes,
        "modified_at": scanned_file.modified_at,
    }
    sha256 = getattr(scanned_file, "sha256", None)
    if sha256 is not None:
        payload["sha256"] = sha256
    return payload


def _file_tree_node(scanned_file: RepoFile) -> dict[str, object]:
    return {
        "type": "file",
        "name": scanned_file.path.rsplit("/", 1)[-1],
        **file_payload(scanned_file),
    }


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
