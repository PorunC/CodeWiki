import warnings
from contextlib import contextmanager
from dataclasses import dataclass

import networkx as nx

from backend.app.db.records import GraphCommunityRecord
from backend.app.services.community_records import CommunityRecordBuilder
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


@dataclass(frozen=True)
class CommunityDetectionResult:
    communities: list[GraphCommunityRecord]
    algorithm: str


class CommunityDetector:
    def __init__(self, *, record_builder: CommunityRecordBuilder | None = None) -> None:
        self.record_builder = record_builder or CommunityRecordBuilder()

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
            self.record_builder.build(repo_id, index, node_ids, node_by_id, edges, algorithm)
            for index, node_ids in enumerate(_rank_communities(communities, node_by_id)[:MAX_COMMUNITIES])
            if node_ids
        ]
        return CommunityDetectionResult(communities=records, algorithm=algorithm)


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
    with _suppress_graspologic_dependency_warnings():
        try:
            from graspologic.partition import leiden
        except ImportError:
            return None

    isolated_node_ids = {str(node_id) for node_id in nx.isolates(graph)}
    partition_graph = graph.copy()
    partition_graph.remove_nodes_from(isolated_node_ids)
    if partition_graph.number_of_nodes() == 0:
        return [{node_id} for node_id in sorted(isolated_node_ids)]

    try:
        with _suppress_graspologic_dependency_warnings():
            try:
                partition = leiden(
                    partition_graph,
                    weight_attribute="weight",
                    random_seed=42,
                )
            except TypeError:
                partition = leiden(partition_graph, weight_attribute="weight")
    except Exception as exc:
        raise RuntimeError("graspologic Leiden community detection failed") from exc

    if not isinstance(partition, dict):
        raise RuntimeError("graspologic Leiden returned an unsupported partition shape")

    by_cluster: dict[object, set[str]] = {}
    for node_id, cluster_id in partition.items():
        by_cluster.setdefault(cluster_id, set()).add(str(node_id))

    assigned_node_ids = set().union(*by_cluster.values()) if by_cluster else set()
    missing_node_ids = {str(node_id) for node_id in partition_graph.nodes} - assigned_node_ids
    missing_node_ids.update(isolated_node_ids)
    for node_id in missing_node_ids:
        by_cluster[f"singleton:{node_id}"] = {node_id}

    return [community for community in by_cluster.values() if community]


@contextmanager
def _suppress_graspologic_dependency_warnings():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Please import `random` from the `scipy\.sparse` namespace.*",
            category=DeprecationWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r"The keyword argument 'nopython=False' was supplied.*",
            category=Warning,
        )
        yield


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
