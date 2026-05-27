from __future__ import annotations

from collections import deque
from fnmatch import fnmatch
from typing import Any

from backend.app.services.graph.models import CodeGraphEdge, CodeGraphNode


def file_dependents(
    edges: list[CodeGraphEdge],
    node_by_id: dict[str, CodeGraphNode],
) -> dict[str, set[str]]:
    dependents: dict[str, set[str]] = {}
    for edge in edges:
        if edge.type not in {"imports", "calls", "references", "routes_to", "inherits", "implements"}:
            continue
        source = node_by_id.get(edge.source_id)
        target = node_by_id.get(edge.target_id)
        if source is None or target is None:
            continue
        if not source.file_path or not target.file_path or source.file_path == target.file_path:
            continue
        dependents.setdefault(target.file_path, set()).add(source.file_path)
    return dependents


def transitive_file_dependents(
    changed_files: list[str],
    dependents_by_file: dict[str, set[str]],
    *,
    max_depth: int,
) -> list[str]:
    affected: set[str] = set()
    queue: deque[tuple[str, int]] = deque((file_path, 0) for file_path in changed_files)
    visited = set(changed_files)
    while queue:
        file_path, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for dependent in sorted(dependents_by_file.get(file_path, set())):
            if dependent in visited:
                continue
            visited.add(dependent)
            affected.add(dependent)
            queue.append((dependent, depth + 1))
    return sorted(affected)


def is_test_file(file_path: str, test_glob: str | None) -> bool:
    normalized = file_path.lower().replace("\\", "/")
    if test_glob:
        return fnmatch(file_path, test_glob)
    name = normalized.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or name.endswith("_test.go")
        or name.endswith("_test.py")
        or "/tests/" in normalized
        or "/test/" in normalized
        or "/__tests__/" in normalized
        or "/e2e/" in normalized
        or "/spec/" in normalized
    )


def page_source_files(source_refs: list[dict[str, Any]]) -> set[str]:
    files: set[str] = set()
    for ref in source_refs:
        file_path = ref.get("file_path")
        if isinstance(file_path, str) and file_path:
            files.add(file_path)
    return files
