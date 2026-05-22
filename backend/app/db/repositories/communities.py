from sqlalchemy import delete, select

from backend.app.db.batching import chunks, write_batch_size
from backend.app.db.utils import now_iso
from backend.app.models import GraphCommunityEdgeRecord, GraphCommunityRecord


class GraphCommunityRepositoryMixin:
    def upsert_graph_community(self, community: GraphCommunityRecord) -> GraphCommunityRecord:
        with self.orm_session() as session:
            record = session.get(GraphCommunityRecord, community.id)
            if record is None:
                session.add(_clone_community(community))
            else:
                record.name = community.name
                record.level = community.level
                record.parent_id = community.parent_id
                record.rank = community.rank
                record.node_ids = community.node_ids
                record.summary = community.summary
                record.summary_hash = community.summary_hash
        return community

    def replace_graph_communities(
        self,
        repo_id: str,
        communities: list[GraphCommunityRecord],
    ) -> None:
        with self.orm_session() as session:
            session.execute(delete(GraphCommunityRecord).where(GraphCommunityRecord.repo_id == repo_id))
            session.commit()
            _insert_graph_communities(
                session,
                self.dialect,
                communities,
                write_batch_size(self.dialect_name),
            )

    def replace_graph_community_edges(
        self,
        repo_id: str,
        edges: list[GraphCommunityEdgeRecord],
    ) -> None:
        with self.orm_session() as session:
            session.execute(
                delete(GraphCommunityEdgeRecord).where(GraphCommunityEdgeRecord.repo_id == repo_id)
            )
            session.commit()
            _insert_graph_community_edges(
                session,
                self.dialect,
                edges,
                write_batch_size(self.dialect_name),
            )

    def list_graph_communities(self, repo_id: str) -> list[GraphCommunityRecord]:
        with self.orm_session() as session:
            return list(
                session.scalars(
                    select(GraphCommunityRecord)
                    .where(GraphCommunityRecord.repo_id == repo_id)
                    .order_by(GraphCommunityRecord.level, GraphCommunityRecord.parent_id, GraphCommunityRecord.rank, GraphCommunityRecord.name)
                )
            )

    def list_graph_community_edges(self, repo_id: str) -> list[GraphCommunityEdgeRecord]:
        with self.orm_session() as session:
            return list(
                session.scalars(
                    select(GraphCommunityEdgeRecord)
                    .where(GraphCommunityEdgeRecord.repo_id == repo_id)
                    .order_by(
                        GraphCommunityEdgeRecord.type,
                        GraphCommunityEdgeRecord.source_community_id,
                        GraphCommunityEdgeRecord.target_community_id,
                    )
                )
            )


def _clone_community(community: GraphCommunityRecord) -> GraphCommunityRecord:
    return GraphCommunityRecord(**community.as_record_dict())


def _clone_community_edge(edge: GraphCommunityEdgeRecord) -> GraphCommunityEdgeRecord:
    return GraphCommunityEdgeRecord(**edge.as_record_dict())


def _insert_graph_communities(
    session,
    dialect,
    communities: list[GraphCommunityRecord],
    batch_size: int,
) -> None:
    if not communities:
        return
    statement = dialect.insert_ignore(GraphCommunityRecord.__table__, ["id"])
    for batch in chunks(communities, batch_size):
        session.execute(statement, [_community_mapping(community) for community in batch])
        session.commit()


def _insert_graph_community_edges(
    session,
    dialect,
    edges: list[GraphCommunityEdgeRecord],
    batch_size: int,
) -> None:
    if not edges:
        return
    statement = dialect.insert_ignore(GraphCommunityEdgeRecord.__table__, ["id"])
    for batch in chunks(edges, batch_size):
        session.execute(statement, [_community_edge_mapping(edge) for edge in batch])
        session.commit()


def _community_mapping(community: GraphCommunityRecord) -> dict[str, object]:
    return {
        "id": community.id,
        "repo_id": community.repo_id,
        "name": community.name,
        "level": community.level or 0,
        "parent_id": community.parent_id,
        "rank": community.rank or 0,
        "node_ids_json": community.node_ids,
        "summary": community.summary,
        "summary_hash": community.summary_hash,
        "created_at": community.created_at or now_iso(),
    }


def _community_edge_mapping(edge: GraphCommunityEdgeRecord) -> dict[str, object]:
    return {
        "id": edge.id,
        "repo_id": edge.repo_id,
        "source_community_id": edge.source_community_id,
        "target_community_id": edge.target_community_id,
        "type": edge.type,
        "weight": edge.weight if edge.weight is not None else 1.0,
        "confidence": edge.confidence if edge.confidence is not None else 1.0,
        "reason": edge.reason,
        "evidence_edge_ids_json": edge.evidence_edge_ids,
        "created_at": edge.created_at or now_iso(),
    }
