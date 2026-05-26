from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from backend.app.services.graph import CodeGraphEdge, CodeGraphNode


@dataclass
class ModuleCandidateDraft:
    path: str
    files: set[str] = field(default_factory=set)
    node_types: Counter[str] = field(default_factory=Counter)
    symbols: list[dict[str, str]] = field(default_factory=list)
    edge_types: Counter[str] = field(default_factory=Counter)


class CatalogModuleCandidatePlanner:
    def build(
        self,
        nodes: list[CodeGraphNode],
        edges: list[CodeGraphEdge],
    ) -> list[dict[str, object]]:
        groups: dict[str, ModuleCandidateDraft] = {}
        node_module: dict[str, str] = {}
        for node in nodes:
            file_path = node.file_path or ""
            if not file_path:
                continue
            module_path = self.module_path(file_path)
            node_module[node.id] = module_path
            group = groups.setdefault(module_path, ModuleCandidateDraft(path=module_path))
            group.files.add(file_path)
            group.node_types[node.type] += 1
            if node.type != "file" and len(group.symbols) < 18:
                group.symbols.append(
                    {
                        "name": node.name,
                        "type": node.type,
                        "file_path": file_path,
                    }
                )

        for edge in edges:
            source_module = node_module.get(edge.source_id)
            target_module = node_module.get(edge.target_id)
            if not source_module or source_module != target_module:
                continue
            edge_group = groups.get(source_module)
            if edge_group is not None:
                edge_group.edge_types[edge.type] += 1

        candidates = [self._candidate_payload(group) for group in groups.values()]
        return sorted(
            candidates,
            key=lambda item: (-_candidate_file_count(item), str(item["path"])),
        )[:36]

    def _candidate_payload(self, group: ModuleCandidateDraft) -> dict[str, object]:
        files = sorted(group.files)
        return {
            "path": group.path,
            "file_count": len(files),
            "files": files[:12],
            "node_types": dict(group.node_types.most_common(8)),
            "edge_types": dict(group.edge_types.most_common(8)),
            "symbols": group.symbols,
            "split_hint": self.split_hint(group.path, files, group.node_types),
        }

    def module_path(self, file_path: str) -> str:
        parts = PurePosixPath(file_path).parts
        if len(parts) <= 1:
            return "."
        directory_parts = parts[:-1]
        if not directory_parts:
            return "."
        if directory_parts[0] in {"backend", "frontend"} and len(directory_parts) >= 3:
            return "/".join(directory_parts[:4])
        return "/".join(directory_parts[:3])

    def split_hint(self, path: str, files: list[str], node_types: Counter[str]) -> str:
        names = {PurePosixPath(file_path).name.lower() for file_path in files}
        if any("api" in file_path or "routes" in file_path for file_path in files):
            return (
                "Consider separate pages for public routes, request/response contracts, "
                "and service delegation."
            )
        if any(name in names for name in {"models.py", "schema.py", "schemas.py", "database.py"}):
            return "Consider separate pages for data models, repositories, persistence, and migrations."
        if any("component" in node_type or node_type in {"component", "hook"} for node_type in node_types):
            return "Consider separate pages for UI views, reusable components, hooks, and user workflows."
        if len(files) >= 6:
            return f"Large module {path}; split by workflow stage, public surface, and extension point."
        if len(files) >= 3:
            return f"Medium module {path}; use at least one focused implementation leaf page."
        return f"Small module {path}; merge into a nearby broader page unless it is a public surface."


def _candidate_file_count(item: dict[str, object]) -> int:
    value = item.get("file_count")
    return value if isinstance(value, int) else 0
