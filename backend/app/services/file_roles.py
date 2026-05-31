from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from backend.app.services.graph.models import CodeGraphEdge, CodeGraphNode

LOCKFILE_NAMES = {"uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
GENERATED_DIR_NAMES = {
    ".next",
    ".nuxt",
    ".svelte-kit",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "out",
    "target",
}
GENERATED_FILE_SUFFIXES = {
    ".bundle.js",
    ".bundle.css",
    ".d.ts",
    ".generated.py",
    ".generated.ts",
    ".generated.tsx",
    ".min.css",
    ".min.js",
}
GENERATED_FILE_NAMES = LOCKFILE_NAMES
VENDOR_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "node_modules",
    "site-packages",
    "vendor",
    "vendors",
    "venv",
}
TEST_DIR_NAMES = {"__tests__", "e2e", "spec", "specs", "test", "tests"}


def normalize_file_path(file_path: str) -> str:
    return file_path.replace("\\", "/").strip("/")


def is_test_file(file_path: str, test_glob: str | None = None) -> bool:
    normalized = normalize_file_path(file_path)
    lowered = normalized.lower()
    if test_glob and fnmatch(normalized, test_glob):
        return True
    name = lowered.rsplit("/", 1)[-1]
    parts = set(PurePosixPath(lowered).parts)
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("_test.go")
        or ".test." in name
        or ".spec." in name
        or bool(parts & TEST_DIR_NAMES)
    )


def is_generated_file(file_path: str) -> bool:
    normalized = normalize_file_path(file_path)
    lowered = normalized.lower()
    name = lowered.rsplit("/", 1)[-1]
    parts = set(PurePosixPath(lowered).parts)
    return (
        name in GENERATED_FILE_NAMES
        or any(name.endswith(suffix) for suffix in GENERATED_FILE_SUFFIXES)
        or bool(parts & GENERATED_DIR_NAMES)
    )


def is_vendor_file(file_path: str) -> bool:
    parts = set(PurePosixPath(normalize_file_path(file_path).lower()).parts)
    return bool(parts & VENDOR_DIR_NAMES)


def is_wiki_noise_file(file_path: str) -> bool:
    return is_test_file(file_path) or is_generated_file(file_path) or is_vendor_file(file_path)


def is_wiki_noise_node(node: CodeGraphNode) -> bool:
    if node.metadata.get("external"):
        return True
    return bool(node.file_path and is_wiki_noise_file(node.file_path))


def filter_wiki_graph(
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
) -> tuple[list[CodeGraphNode], list[CodeGraphEdge]]:
    filtered_nodes = [node for node in nodes if not is_wiki_noise_node(node)]
    node_ids = {node.id for node in filtered_nodes}
    filtered_edges = [
        edge for edge in edges if edge.source_id in node_ids and edge.target_id in node_ids
    ]
    return filtered_nodes, filtered_edges
