from collections.abc import Callable
from pathlib import PurePosixPath

from backend.app.services.ast_parser import AstSymbol
from backend.app.services.graph.ids import directory_node_id, module_node_id
from backend.app.services.graph.models import CodeGraphNode
from backend.app.services.graph_provenance import with_node_provenance
from backend.app.services.repo_scanner import RepoDescriptor, ScannedFile


def repository_node(repo: RepoDescriptor) -> CodeGraphNode:
    return CodeGraphNode(
        id=f"{repo.id}:repository",
        repo_id=repo.id,
        type="repository",
        name=repo.name,
        file_path="",
        metadata={"path": repo.path, "source_type": repo.source_type},
    )


def file_node(repo_id: str, scanned_file: ScannedFile, node_id: str) -> CodeGraphNode:
    metadata = {
        "absolute_path": scanned_file.absolute_path,
        "is_source": scanned_file.is_source,
        "size_bytes": scanned_file.size_bytes,
        "modified_at": scanned_file.modified_at,
    }
    if scanned_file.last_commit_at is not None:
        metadata["last_commit_at"] = scanned_file.last_commit_at
    return CodeGraphNode(
        id=node_id,
        repo_id=repo_id,
        type="file",
        name=PurePosixPath(scanned_file.path).name,
        file_path=scanned_file.path,
        start_line=1,
        language=scanned_file.language,
        symbol_id=f"file:{scanned_file.path}",
        hash=scanned_file.sha256,
        metadata=metadata,
    )


def directory_node(repo_id: str, directory_path: str) -> CodeGraphNode:
    return CodeGraphNode(
        id=directory_node_id(repo_id, directory_path),
        repo_id=repo_id,
        type="directory",
        name=PurePosixPath(directory_path).name,
        file_path=directory_path,
        metadata={"path": directory_path},
    )


def symbol_node(repo_id: str, symbol: AstSymbol, node_id: str) -> CodeGraphNode:
    return CodeGraphNode(
        id=node_id,
        repo_id=repo_id,
        type=symbol.type,
        name=symbol.name,
        file_path=symbol.file_path,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        language=symbol.language,
        symbol_id=symbol.id,
        hash=symbol.hash,
        metadata={
            "signature": symbol.signature,
            "docstring": symbol.docstring,
            "exports": symbol.exports,
            "bases": symbol.bases,
            "decorators": symbol.decorators,
            "calls": symbol.calls,
            **symbol.metadata,
        },
    )


def module_node(repo_id: str, name: str, *, kind: str | None = None) -> CodeGraphNode:
    metadata: dict[str, object] = {"external": True}
    if kind is not None:
        metadata["kind"] = kind
    return CodeGraphNode(
        id=module_node_id(repo_id, name),
        repo_id=repo_id,
        type="module",
        name=name,
        metadata=metadata,
    )


def ensure_directory_nodes(
    *,
    repo_id: str,
    file_path: str,
    repo_node_id: str,
    directory_nodes: dict[str, str],
    add_node: Callable[[CodeGraphNode], None],
    add_edge: Callable[..., None],
) -> str:
    parent_id = repo_node_id
    parts = PurePosixPath(file_path).parts[:-1]
    current_parts: list[str] = []
    for part in parts:
        current_parts.append(part)
        directory_path = "/".join(current_parts)
        directory_id = directory_node_id(repo_id, directory_path)
        if directory_path not in directory_nodes:
            directory_nodes[directory_path] = directory_id
            add_node(directory_node(repo_id, directory_path))
            add_edge(parent_id, directory_id, "contains")
        parent_id = directory_id
    return parent_id


def node_metadata_with_provenance(node: CodeGraphNode) -> dict[str, object]:
    metadata = dict(node.metadata)
    source, kind, confidence = node_provenance_defaults(node, metadata)
    return with_node_provenance(
        metadata,
        source=source,
        kind=kind,
        confidence=confidence,
        evidence=node_evidence(node),
    )


def node_provenance_defaults(
    node: CodeGraphNode,
    metadata: dict[str, object],
) -> tuple[str, str, float]:
    if node.type == "repository":
        return "repo_scanner", "synthetic_root", 1.0
    if node.type == "directory":
        return "repo_scanner", "synthetic_directory", 1.0
    if node.type == "file":
        return "repo_scanner", "extracted", 1.0
    if node.type == "module":
        if metadata.get("kind") == "type_reference":
            return "graph_builder", "inferred_external_reference", 0.65
        return "graph_builder", "external_reference", 1.0
    if node.symbol_id:
        return "ast_parser", "extracted", 1.0
    return "graph_builder", "synthetic", 1.0


def node_evidence(node: CodeGraphNode) -> list[str]:
    evidence: list[str] = [f"type={node.type}"]
    if node.file_path:
        evidence.append(f"file_path={node.file_path}")
    if node.start_line is not None:
        evidence.append(f"start_line={node.start_line}")
    if node.end_line is not None:
        evidence.append(f"end_line={node.end_line}")
    return evidence
