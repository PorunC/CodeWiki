from pathlib import PurePosixPath

from backend.app.services.graph.models import CodeGraphNode
from backend.app.services.graph_provenance import with_node_provenance
from backend.app.services.repo_scanner import ScannedFile


def file_node(repo_id: str, scanned_file: ScannedFile, node_id: str) -> CodeGraphNode:
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
        metadata={
            "absolute_path": scanned_file.absolute_path,
            "is_source": scanned_file.is_source,
            "size_bytes": scanned_file.size_bytes,
            "modified_at": scanned_file.modified_at,
        },
    )


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
