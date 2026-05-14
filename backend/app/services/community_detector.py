import re
from dataclasses import dataclass
from hashlib import sha1, sha256

import networkx as nx

from backend.app.db.records import GraphCommunityRecord
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode

COMMUNITY_NODE_TYPES = {"file", "config", "class", "function", "method", "schema", "endpoint"}
COMMUNITY_EDGE_WEIGHTS = {
    "calls": 1.0,
    "routes_to": 1.0,
    "inherits": 0.9,
    "implements": 0.86,
    "imports": 0.75,
    "exports": 0.65,
    "references": 0.62,
    "uses_config": 0.58,
    "defines": 0.5,
    "contains": 0.42,
}
MAX_COMMUNITIES = 32
MAX_SUMMARY_FILES = 8
MAX_SUMMARY_SYMBOLS = 10
MAX_SUMMARY_EDGES = 8


@dataclass(frozen=True)
class CommunityDetectionResult:
    communities: list[GraphCommunityRecord]
    algorithm: str


class CommunityDetector:
    def detect(
        self,
        repo_id: str,
        nodes: list[CodeGraphNode],
        edges: list[CodeGraphEdge],
    ) -> CommunityDetectionResult:
        node_by_id = {
            node.id: node
            for node in nodes
            if node.type in COMMUNITY_NODE_TYPES and not node.metadata.get("external")
        }
        graph = nx.Graph()
        for node_id in node_by_id:
            graph.add_node(node_id)

        for edge in edges:
            if edge.source_id not in node_by_id or edge.target_id not in node_by_id:
                continue
            edge_weight = COMMUNITY_EDGE_WEIGHTS.get(edge.type)
            if edge_weight is None:
                continue
            weight = max(0.01, edge_weight * edge.confidence)
            if graph.has_edge(edge.source_id, edge.target_id):
                graph[edge.source_id][edge.target_id]["weight"] += weight
            else:
                graph.add_edge(edge.source_id, edge.target_id, weight=weight)

        communities, algorithm = _partition(graph)
        records = [
            self._community_record(repo_id, index, node_ids, node_by_id, edges, algorithm)
            for index, node_ids in enumerate(_rank_communities(communities, node_by_id)[:MAX_COMMUNITIES])
            if node_ids
        ]
        return CommunityDetectionResult(communities=records, algorithm=algorithm)

    def _community_record(
        self,
        repo_id: str,
        index: int,
        node_ids: list[str],
        node_by_id: dict[str, CodeGraphNode],
        edges: list[CodeGraphEdge],
        algorithm: str,
    ) -> GraphCommunityRecord:
        name = _community_name(index, node_ids, node_by_id)
        summary = _community_summary(name, node_ids, node_by_id, edges, algorithm)
        digest = sha1("|".join(sorted(node_ids)).encode("utf-8")).hexdigest()[:16]
        return GraphCommunityRecord(
            id=f"{repo_id}:community:0:{digest}",
            repo_id=repo_id,
            name=name,
            level=0,
            node_ids=sorted(node_ids),
            summary=summary,
            summary_hash=sha256(summary.encode("utf-8")).hexdigest(),
            created_at=None,
        )


def _partition(graph: nx.Graph) -> tuple[list[set[str]], str]:
    if graph.number_of_nodes() == 0:
        return [], "empty"
    if graph.number_of_edges() == 0:
        return [set(component) for component in nx.connected_components(graph)], "connected_components"

    leiden_communities = _graspologic_leiden_communities(graph)
    if leiden_communities is not None:
        return leiden_communities, "graspologic_leiden"

    try:
        communities = nx.algorithms.community.louvain_communities(
            graph,
            weight="weight",
            seed=42,
        )
        return [set(community) for community in communities], "networkx_louvain"
    except Exception:
        communities = nx.algorithms.community.greedy_modularity_communities(
            graph,
            weight="weight",
        )
        return [set(community) for community in communities], "networkx_greedy_modularity"


def _graspologic_leiden_communities(graph: nx.Graph) -> list[set[str]] | None:
    try:
        from graspologic.partition import leiden
    except ImportError:
        return None

    try:
        try:
            partition = leiden(
                graph,
                weight_attribute="weight",
                random_seed=42,
            )
        except TypeError:
            partition = leiden(graph, weight_attribute="weight")
    except Exception as exc:
        raise RuntimeError("graspologic Leiden community detection failed") from exc

    if not isinstance(partition, dict):
        raise RuntimeError("graspologic Leiden returned an unsupported partition shape")

    by_cluster: dict[object, set[str]] = {}
    for node_id, cluster_id in partition.items():
        by_cluster.setdefault(cluster_id, set()).add(str(node_id))

    assigned_node_ids = set().union(*by_cluster.values()) if by_cluster else set()
    missing_node_ids = {str(node_id) for node_id in graph.nodes} - assigned_node_ids
    for node_id in missing_node_ids:
        by_cluster[f"singleton:{node_id}"] = {node_id}

    return [community for community in by_cluster.values() if community]


def _rank_communities(
    communities: list[set[str]],
    node_by_id: dict[str, CodeGraphNode],
) -> list[list[str]]:
    return [
        sorted(community)
        for community in sorted(
            communities,
            key=lambda item: (-len(item), _community_sort_label(item, node_by_id)),
        )
    ]


def _community_sort_label(
    node_ids: set[str],
    node_by_id: dict[str, CodeGraphNode],
) -> str:
    labels = [
        node.file_path or node.name
        for node_id in node_ids
        if (node := node_by_id.get(node_id)) is not None
    ]
    return min(labels) if labels else ""


def _community_name(
    index: int,
    node_ids: list[str],
    node_by_id: dict[str, CodeGraphNode],
) -> str:
    files = _community_files(node_ids, node_by_id)
    symbols = _community_symbols(node_ids, node_by_id)
    label = _name_from_files(files) or _name_from_symbols(symbols) or "Unclassified Code Area"
    return _dedupe_words(label)


def _community_summary(
    name: str,
    node_ids: list[str],
    node_by_id: dict[str, CodeGraphNode],
    edges: list[CodeGraphEdge],
    algorithm: str,
) -> str:
    node_id_set = set(node_ids)
    files = _community_files(node_ids, node_by_id)
    symbols = _community_symbols(node_ids, node_by_id)
    internal_edges = [
        edge
        for edge in edges
        if edge.source_id in node_id_set and edge.target_id in node_id_set
    ]
    boundary_edges = [
        edge
        for edge in edges
        if (edge.source_id in node_id_set) ^ (edge.target_id in node_id_set)
    ]

    lines = [
        f"{name} was detected by {algorithm} and contains {len(node_ids)} graph nodes.",
    ]
    if files:
        lines.append(f"Key files: {', '.join(files[:MAX_SUMMARY_FILES])}.")
    if symbols:
        lines.append(f"Key symbols: {', '.join(symbols[:MAX_SUMMARY_SYMBOLS])}.")
    if internal_edges:
        lines.append(f"Internal relationships: {_edge_summary(internal_edges, node_by_id)}.")
    if boundary_edges:
        lines.append(f"Boundary relationships: {_edge_summary(boundary_edges, node_by_id)}.")
    return " ".join(lines)


def _community_files(
    node_ids: list[str],
    node_by_id: dict[str, CodeGraphNode],
) -> list[str]:
    return sorted(
        {
            node.file_path
            for node_id in node_ids
            if (node := node_by_id.get(node_id)) is not None and node.file_path
        }
    )


def _name_from_files(files: list[str]) -> str:
    labels = [_file_label(file_path) for file_path in files]
    labels = [label for label in labels if label and label.lower() not in {"index", "main"}]
    if not labels:
        return ""
    unique_labels = _unique_preserve_order(labels)
    if len(unique_labels) == 1:
        return unique_labels[0]
    if len(unique_labels) == 2:
        return f"{unique_labels[0]} and {unique_labels[1]}"

    directories = _meaningful_directories(files)
    if directories and len(set(directories)) == 1:
        return f"{_humanize_stem(directories[0])}: {unique_labels[0]} and {unique_labels[1]}"
    return f"{unique_labels[0]}, {unique_labels[1]}, and {unique_labels[2]}"


def _file_label(file_path: str) -> str:
    file_name = file_path.rsplit("/", 1)[-1]
    if file_name.startswith("__init__."):
        package_name = _package_name(file_path)
        return f"{_humanize_stem(package_name)} Package" if package_name else "Python Package"
    return _humanize_stem(_file_stem(file_name))


def _file_stem(file_name: str) -> str:
    if file_name.startswith("."):
        file_name = file_name.lstrip(".")
    return file_name.rsplit(".", 1)[0]


def _package_name(file_path: str) -> str:
    parts = file_path.split("/")[:-1]
    return parts[-1] if parts else ""


def _name_from_symbols(symbols: list[str]) -> str:
    for symbol in symbols:
        name = symbol.split(" (", 1)[0].strip()
        if name and not name.startswith("_"):
            return _humanize_stem(name)
    return ""


def _meaningful_directories(files: list[str]) -> list[str]:
    ignored = {"backend", "frontend", "src", "app", "tests", "test"}
    directories = []
    for file_path in files:
        parts = file_path.split("/")[:-1]
        meaningful = [part for part in parts if part not in ignored]
        if meaningful:
            directories.append(meaningful[-1])
    return directories


def _humanize_stem(value: str) -> str:
    value = re.sub(r"^test_", "", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = value.replace("_", " ").replace("-", " ").strip()
    words = [word for word in value.split() if word]
    if not words:
        return ""
    return " ".join(word if word.isupper() else word.capitalize() for word in words)


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def _dedupe_words(value: str) -> str:
    words = value.split()
    deduped: list[str] = []
    for word in words:
        if deduped and deduped[-1].lower().strip(":,") == word.lower().strip(":,"):
            continue
        deduped.append(word)
    return " ".join(deduped)


def _community_symbols(
    node_ids: list[str],
    node_by_id: dict[str, CodeGraphNode],
) -> list[str]:
    symbols = [
        f"{node.name} ({node.type})"
        for node_id in node_ids
        if (node := node_by_id.get(node_id)) is not None and node.type != "file"
    ]
    return sorted(symbols)


def _edge_summary(
    edges: list[CodeGraphEdge],
    node_by_id: dict[str, CodeGraphNode],
) -> str:
    samples = []
    for edge in sorted(edges, key=lambda item: (-item.confidence, item.type, item.source_id))[
        :MAX_SUMMARY_EDGES
    ]:
        source = node_by_id.get(edge.source_id)
        target = node_by_id.get(edge.target_id)
        source_name = source.name if source is not None else edge.source_id.rsplit(":", 1)[-1]
        target_name = target.name if target is not None else edge.target_id.rsplit(":", 1)[-1]
        samples.append(f"{source_name} -[{edge.type}]-> {target_name}")
    return "; ".join(samples)
