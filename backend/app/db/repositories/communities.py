from sqlalchemy import delete, select

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
            session.add_all(_clone_community(community) for community in communities)

    def replace_graph_community_edges(
        self,
        repo_id: str,
        edges: list[GraphCommunityEdgeRecord],
    ) -> None:
        with self.orm_session() as session:
            session.execute(
                delete(GraphCommunityEdgeRecord).where(GraphCommunityEdgeRecord.repo_id == repo_id)
            )
            session.add_all(_clone_community_edge(edge) for edge in edges)

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
