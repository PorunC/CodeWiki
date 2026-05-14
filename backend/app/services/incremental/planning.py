from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.incremental.models import IncrementalUpdatePlan
from backend.app.services.repo_scanner import RepoScanResult


def _plan_from_scan(
    repo_id: str,
    scan: RepoScanResult,
    current_nodes: list[CodeGraphNode],
    *,
    candidate_paths: set[str] | None = None,
    detection_strategy: str = "sha256",
    base_commit: str | None = None,
    head_commit: str | None = None,
) -> IncrementalUpdatePlan:
    current_file_hashes = {
        node.file_path: node.hash
        for node in current_nodes
        if node.type == "file" and node.file_path
    }
    scanned_file_hashes = {scanned_file.path: scanned_file.sha256 for scanned_file in scan.files}

    hash_changed_paths = {
        path
        for path, file_hash in scanned_file_hashes.items()
        if path in current_file_hashes and current_file_hashes[path] != file_hash
    }
    hash_new_paths = {path for path in scanned_file_hashes if path not in current_file_hashes}
    hash_deleted_paths = {path for path in current_file_hashes if path not in scanned_file_hashes}
    paths_to_check = candidate_paths
    if paths_to_check is not None:
        paths_to_check = set(paths_to_check) | hash_changed_paths | hash_new_paths | hash_deleted_paths

    changed_files = sorted(
        path
        for path in (paths_to_check or set(scanned_file_hashes))
        if path in scanned_file_hashes
        and path in current_file_hashes
        and current_file_hashes[path] != scanned_file_hashes[path]
    )
    new_files = sorted(
        path
        for path in (paths_to_check or set(scanned_file_hashes))
        if path in scanned_file_hashes and path not in current_file_hashes
    )
    deleted_files = sorted(
        path
        for path in (paths_to_check or set(current_file_hashes))
        if path in current_file_hashes and path not in scanned_file_hashes
    )
    unchanged_files = sorted(
        path
        for path, file_hash in scanned_file_hashes.items()
        if current_file_hashes.get(path) == file_hash
    )
    return IncrementalUpdatePlan(
        repo_id=repo_id,
        changed_files=changed_files,
        new_files=new_files,
        deleted_files=deleted_files,
        unchanged_files=unchanged_files,
        detection_strategy=detection_strategy,
        base_commit=base_commit,
        head_commit=head_commit,
    )


def _affected_graph_refs(
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
    file_paths: list[str],
) -> list[str]:
    file_path_set = set(file_paths)
    affected_node_ids = {
        node.id
        for node in nodes
        if node.file_path in file_path_set
    }
    affected_edge_ids = {
        edge.id
        for edge in edges
        if edge.source_id in affected_node_ids or edge.target_id in affected_node_ids
    }
    return sorted(affected_node_ids | affected_edge_ids)
