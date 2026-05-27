from collections import Counter, defaultdict
from dataclasses import dataclass, field
from hashlib import sha1

from backend.app.db.records import GraphCommunityEdgeRecord, GraphCommunityRecord
from backend.app.services.graph import CodeGraphEdge

MAX_EVIDENCE_EDGE_IDS = 24
COMMUNITY_DEPENDENCY_EDGE_TYPES = {
    "calls": "calls_into",
    "imports": "imports_from",
    "exports": "imports_from",
    "routes_to": "routes_to",
}
IGNORED_AGGREGATE_EDGE_TYPES = {"contains", "defines"}


@dataclass
class _Aggregate:
    weight: float = 0.0
    confidence_total: float = 0.0
    count: int = 0
    evidence_edge_ids: list[str] = field(default_factory=list)
    source_types: Counter[str] = field(default_factory=Counter)


class CommunityEdgeBuilder:
    def build(
        self,
        repo_id: str,
        communities: list[GraphCommunityRecord],
        code_edges: list[CodeGraphEdge],
    ) -> list[GraphCommunityEdgeRecord]:
        contains_edges = self._contains_edges(repo_id, communities)
        dependency_edges = self._dependency_edges(repo_id, communities, code_edges)
        return [*contains_edges, *dependency_edges]

    def _contains_edges(
        self,
        repo_id: str,
        communities: list[GraphCommunityRecord],
    ) -> list[GraphCommunityEdgeRecord]:
        community_ids = {community.id for community in communities}
        edges = []
        for community in communities:
            if not community.parent_id or community.parent_id not in community_ids:
                continue
            edges.append(
                GraphCommunityEdgeRecord(
                    id=_edge_id(repo_id, community.parent_id, community.id, "contains"),
                    repo_id=repo_id,
                    source_community_id=community.parent_id,
                    target_community_id=community.id,
                    type="contains",
                    weight=1.0,
                    confidence=1.0,
                    reason="Parent community contains this child community.",
                    evidence_edge_ids=[],
                    created_at=None,
                )
            )
        return edges

    def _dependency_edges(
        self,
        repo_id: str,
        communities: list[GraphCommunityRecord],
        code_edges: list[CodeGraphEdge],
    ) -> list[GraphCommunityEdgeRecord]:
        parent_ids = {
            community.parent_id
            for community in communities
            if isinstance(community.parent_id, str) and community.parent_id
        }
        leaves = [community for community in communities if community.id not in parent_ids]

        node_to_community: dict[str, str] = {}
        for community in leaves:
            for node_id in community.node_ids:
                node_to_community.setdefault(node_id, community.id)

        aggregates: dict[tuple[str, str, str], _Aggregate] = defaultdict(_Aggregate)
        for edge in code_edges:
            if edge.type in IGNORED_AGGREGATE_EDGE_TYPES:
                continue
            source_community_id = node_to_community.get(edge.source_id)
            target_community_id = node_to_community.get(edge.target_id)
            if (
                source_community_id is None
                or target_community_id is None
                or source_community_id == target_community_id
            ):
                continue
            edge_type = COMMUNITY_DEPENDENCY_EDGE_TYPES.get(edge.type, "depends_on")
            aggregate = aggregates[(source_community_id, target_community_id, edge_type)]
            aggregate.weight += max(0.01, edge.weight)
            aggregate.confidence_total += edge.confidence
            aggregate.count += 1
            aggregate.source_types[edge.type] += 1
            if len(aggregate.evidence_edge_ids) < MAX_EVIDENCE_EDGE_IDS:
                aggregate.evidence_edge_ids.append(edge.id)

        return [
            GraphCommunityEdgeRecord(
                id=_edge_id(repo_id, source_id, target_id, edge_type),
                repo_id=repo_id,
                source_community_id=source_id,
                target_community_id=target_id,
                type=edge_type,
                weight=round(aggregate.weight, 4),
                confidence=round(aggregate.confidence_total / max(aggregate.count, 1), 4),
                reason=_reason(aggregate),
                evidence_edge_ids=aggregate.evidence_edge_ids,
                created_at=None,
            )
            for (source_id, target_id, edge_type), aggregate in sorted(aggregates.items())
        ]


def _edge_id(repo_id: str, source_id: str, target_id: str, edge_type: str) -> str:
    digest = sha1("|".join([source_id, target_id, edge_type]).encode("utf-8")).hexdigest()[:20]
    return f"{repo_id}:community-edge:{digest}"


def _reason(aggregate: _Aggregate) -> str:
    type_counts = ", ".join(
        f"{count} {edge_type}" for edge_type, count in sorted(aggregate.source_types.items())
    )
    return f"Aggregated from {aggregate.count} source graph edges: {type_counts}."
