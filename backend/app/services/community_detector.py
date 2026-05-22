import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha1
from typing import Iterable

import networkx as nx

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
LEAF_RESOLUTION = 2.0
DETAIL_RESOLUTION = 3.0
PARENT_RESOLUTION = 0.5
MAX_COMMUNITIES = 32
MAX_PARENT_COMMUNITIES = 24
MAX_CHILD_COMMUNITIES_PER_PARENT = 12
MIN_CHILD_NODES = 8
MIN_PARENT_NODES = 24
DETAIL_SPLIT_NODE_THRESHOLD = 120
DETAIL_SPLIT_FILE_THRESHOLD = 32
MIN_DETAIL_NODES = 12
MAX_DETAIL_COMMUNITIES_PER_CHILD = 8
MAX_TOTAL_COMMUNITIES = 128
MIN_COMMUNITY_EDGE_WEIGHT = 0.01


@dataclass(frozen=True)
class DetectedCommunity:
    key: str
    node_ids: list[str]
    level: int
    parent_key: str | None
    rank: int


@dataclass(frozen=True)
class CommunityDetectionResult:
    communities: list[DetectedCommunity]
    algorithm: str

    @property
    def partitions(self) -> list[list[str]]:
        return [community.node_ids for community in self.communities]


class CommunityDetector:
    def detect(
        self,
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

        leaf_communities, leaf_algorithm = _partition(graph, resolution=LEAF_RESOLUTION)
        leaf_partitions = _rank_communities(leaf_communities, node_by_id)
        if len(leaf_partitions) <= 1:
            detected = [
                DetectedCommunity(
                    key=_community_key(node_ids),
                    node_ids=node_ids,
                    level=0,
                    parent_key=None,
                    rank=index,
                )
                for index, node_ids in enumerate(leaf_partitions[:MAX_COMMUNITIES])
                if node_ids
            ]
            return CommunityDetectionResult(communities=detected, algorithm=leaf_algorithm)

        community_graph = _build_community_graph(graph, leaf_partitions)
        leaf_partitions = _merge_small_leaf_partitions(leaf_partitions, community_graph)
        community_graph = _build_community_graph(graph, leaf_partitions)
        parent_communities, parent_algorithm = _partition(
            community_graph,
            resolution=PARENT_RESOLUTION,
        )
        parent_partitions = _normalize_parent_partitions(
            parent_communities,
            leaf_partitions,
            community_graph,
        )
        detected = _detected_hierarchy(parent_partitions, leaf_partitions, node_by_id, graph)
        return CommunityDetectionResult(
            communities=detected[:MAX_TOTAL_COMMUNITIES],
            algorithm=f"{leaf_algorithm}+community_graph:{parent_algorithm}",
        )


def _partition(graph: nx.Graph, *, resolution: float = 1.0) -> tuple[list[set[str]], str]:
    if graph.number_of_nodes() == 0:
        return [], "empty"
    if graph.number_of_edges() == 0:
        return [set(component) for component in nx.connected_components(graph)], "connected_components"

    try:
        communities = nx.algorithms.community.louvain_communities(
            graph,
            weight="weight",
            resolution=resolution,
            seed=42,
        )
        return [set(community) for community in communities], "networkx_louvain"
    except Exception:
        leiden_communities = _graspologic_leiden_communities(graph, resolution=resolution)
        if leiden_communities is not None:
            return leiden_communities, "graspologic_leiden"
        communities = nx.algorithms.community.greedy_modularity_communities(
            graph,
            weight="weight",
        )
        return [set(community) for community in communities], "networkx_greedy_modularity"


def _graspologic_leiden_communities(
    graph: nx.Graph,
    *,
    resolution: float,
) -> list[set[str]] | None:
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
                    resolution=resolution,
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


def _build_community_graph(
    source_graph: nx.Graph,
    leaf_partitions: list[list[str]],
) -> nx.Graph:
    graph = nx.Graph()
    node_to_leaf: dict[str, int] = {}
    for index, node_ids in enumerate(leaf_partitions):
        graph.add_node(index)
        for node_id in node_ids:
            node_to_leaf[node_id] = index

    for source_id, target_id, data in source_graph.edges(data=True):
        source_leaf = node_to_leaf.get(str(source_id))
        target_leaf = node_to_leaf.get(str(target_id))
        if source_leaf is None or target_leaf is None or source_leaf == target_leaf:
            continue
        weight = float(data.get("weight") or 1.0)
        if graph.has_edge(source_leaf, target_leaf):
            graph[source_leaf][target_leaf]["weight"] += weight
        else:
            graph.add_edge(source_leaf, target_leaf, weight=weight)
    return graph


def _merge_small_leaf_partitions(
    leaf_partitions: list[list[str]],
    community_graph: nx.Graph,
) -> list[list[str]]:
    merged = [set(node_ids) for node_ids in leaf_partitions]
    removed: set[int] = set()
    for index, node_ids in enumerate(merged):
        if index in removed or len(node_ids) >= MIN_CHILD_NODES:
            continue
        target = _strongest_neighbor(index, community_graph, removed=removed)
        if target is None:
            continue
        weight = float(community_graph[index][target].get("weight") or 0.0)
        if weight < MIN_COMMUNITY_EDGE_WEIGHT:
            continue
        merged[target].update(node_ids)
        removed.add(index)
    return [sorted(node_ids) for index, node_ids in enumerate(merged) if index not in removed and node_ids]


def _normalize_parent_partitions(
    parent_communities: list[set[str]],
    leaf_partitions: list[list[str]],
    community_graph: nx.Graph,
) -> list[list[int]]:
    parent_partitions = [
        sorted(int(index) for index in community if int(index) < len(leaf_partitions))
        for community in parent_communities
    ]
    parent_partitions = [partition for partition in parent_partitions if partition]
    leaf_to_parent = {
        leaf_index: parent_index
        for parent_index, partition in enumerate(parent_partitions)
        for leaf_index in partition
    }
    removed_parents: set[int] = set()
    for parent_index, partition in enumerate(parent_partitions):
        if len(partition) != 1:
            continue
        leaf_index = partition[0]
        if len(leaf_partitions[leaf_index]) >= MIN_PARENT_NODES:
            continue
        target_leaf = _strongest_neighbor(leaf_index, community_graph)
        if target_leaf is None:
            continue
        target_parent = leaf_to_parent.get(target_leaf)
        if target_parent is None or target_parent == parent_index:
            continue
        parent_partitions[target_parent].append(leaf_index)
        leaf_to_parent[leaf_index] = target_parent
        removed_parents.add(parent_index)

    normalized = [
        sorted(set(partition))
        for index, partition in enumerate(parent_partitions)
        if index not in removed_parents and partition
    ]
    normalized.sort(key=lambda item: (-_partition_node_count(item, leaf_partitions), item))
    return normalized[:MAX_PARENT_COMMUNITIES]


def _detected_hierarchy(
    parent_partitions: list[list[int]],
    leaf_partitions: list[list[str]],
    node_by_id: dict[str, CodeGraphNode],
    source_graph: nx.Graph,
) -> list[DetectedCommunity]:
    detected: list[DetectedCommunity] = []
    for parent_rank, leaf_indexes in enumerate(parent_partitions):
        parent_node_ids = sorted(
            set().union(*(set(leaf_partitions[index]) for index in leaf_indexes))
        )
        if not parent_node_ids:
            continue
        parent_key = _community_key(parent_node_ids)
        detected.append(
            DetectedCommunity(
                key=parent_key,
                node_ids=parent_node_ids,
                level=0,
                parent_key=None,
                rank=parent_rank,
            )
        )
        child_partitions = [
            leaf_partitions[index]
            for index in sorted(
                leaf_indexes,
                key=lambda item: (-len(leaf_partitions[item]), _community_sort_label(set(leaf_partitions[item]), node_by_id)),
            )
        ][:MAX_CHILD_COMMUNITIES_PER_PARENT]
        if len(child_partitions) <= 1:
            continue
        for child_rank, child_node_ids in enumerate(child_partitions):
            child_key = _community_key(child_node_ids)
            detected.append(
                DetectedCommunity(
                    key=child_key,
                    node_ids=sorted(child_node_ids),
                    level=1,
                    parent_key=parent_key,
                    rank=child_rank,
                )
            )
            detail_partitions = _detail_partitions(child_node_ids, node_by_id, source_graph)
            if len(detail_partitions) <= 1:
                continue
            for detail_rank, detail_node_ids in enumerate(detail_partitions[:MAX_DETAIL_COMMUNITIES_PER_CHILD]):
                detected.append(
                    DetectedCommunity(
                        key=_community_key(detail_node_ids),
                        node_ids=sorted(detail_node_ids),
                        level=2,
                        parent_key=child_key,
                        rank=detail_rank,
                    )
                )
    return detected


def _detail_partitions(
    node_ids: list[str],
    node_by_id: dict[str, CodeGraphNode],
    source_graph: nx.Graph,
) -> list[list[str]]:
    if len(node_ids) < DETAIL_SPLIT_NODE_THRESHOLD and _file_count(node_ids, node_by_id) < DETAIL_SPLIT_FILE_THRESHOLD:
        return []
    subgraph = source_graph.subgraph(node_ids).copy()
    communities, _algorithm = _partition(subgraph, resolution=DETAIL_RESOLUTION)
    partitions = [
        partition
        for partition in _rank_communities(communities, node_by_id)
        if len(partition) >= MIN_DETAIL_NODES
    ]
    if len(partitions) <= 1:
        return []
    return partitions


def _file_count(node_ids: list[str], node_by_id: dict[str, CodeGraphNode]) -> int:
    return len(
        {
            node.file_path
            for node_id in node_ids
            if (node := node_by_id.get(node_id)) is not None and node.file_path
        }
    )


def _strongest_neighbor(
    node: int,
    graph: nx.Graph,
    *,
    removed: set[int] | None = None,
) -> int | None:
    removed = removed or set()
    candidates = [neighbor for neighbor in graph.neighbors(node) if neighbor not in removed]
    if not candidates:
        return None
    return max(candidates, key=lambda neighbor: float(graph[node][neighbor].get("weight") or 0.0))


def _partition_node_count(parent_partition: list[int], leaf_partitions: list[list[str]]) -> int:
    return sum(len(leaf_partitions[index]) for index in parent_partition)


def _community_key(node_ids: Iterable[str]) -> str:
    return sha1("|".join(sorted(node_ids)).encode("utf-8")).hexdigest()[:16]
