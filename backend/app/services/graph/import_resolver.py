import posixpath
from collections.abc import Callable
from pathlib import PurePosixPath

from backend.app.services.graph.ids import module_node_id
from backend.app.services.graph.models import CodeGraphNode
from backend.app.services.graph.node_factory import module_node


def resolve_import_target(
    import_name: str,
    *,
    from_file_path: str,
    file_nodes: dict[str, str],
) -> str | None:
    for candidate in import_candidates(import_name, from_file_path=from_file_path):
        if candidate in file_nodes:
            return file_nodes[candidate]
    return None


def import_candidates(import_name: str, *, from_file_path: str) -> list[str]:
    candidates: list[str] = []
    from_dir = PurePosixPath(from_file_path).parent.as_posix()
    from_dir = "" if from_dir == "." else from_dir

    if import_name.startswith("."):
        if import_name.startswith("./") or import_name.startswith("../"):
            module_path = posixpath.normpath(posixpath.join(from_dir, import_name))
            candidates.extend(file_candidates(module_path))
        else:
            leading_dots = len(import_name) - len(import_name.lstrip("."))
            rest = import_name[leading_dots:].replace(".", "/")
            parts = [] if from_dir == "" else from_dir.split("/")
            parent = "/".join(parts[: max(len(parts) - leading_dots + 1, 0)])
            module_path = posixpath.normpath(posixpath.join(parent, rest))
            candidates.extend(file_candidates(module_path))
    else:
        parts = import_name.split(".")
        for index in range(len(parts), 0, -1):
            candidates.extend(file_candidates("/".join(parts[:index])))

    return [candidate for candidate in candidates if candidate and not candidate.startswith("../")]


def file_candidates(module_path: str) -> list[str]:
    module_path = module_path.removesuffix("/")
    suffixes = [
        "",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".py",
        "/index.ts",
        "/index.tsx",
        "/index.js",
        "/__init__.py",
    ]
    candidates = []
    for suffix in suffixes:
        candidate = f"{module_path}{suffix}"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def add_import_edges(
    *,
    repo_id: str,
    file_node_id: str | None,
    from_file_path: str,
    imports: list[str],
    file_nodes: dict[str, str],
    add_node: Callable[[CodeGraphNode], None],
    add_edge: Callable[..., None],
) -> None:
    if not file_node_id:
        return
    for import_name in imports:
        local_target_id = resolve_import_target(
            import_name,
            from_file_path=from_file_path,
            file_nodes=file_nodes,
        )
        if local_target_id:
            add_edge(
                file_node_id,
                local_target_id,
                "imports",
                metadata={"import": import_name, "resolved": True},
            )
            continue
        add_node(module_node(repo_id, import_name))
        add_edge(
            file_node_id,
            module_node_id(repo_id, import_name),
            "imports",
            metadata={"import": import_name, "resolved": False},
        )
