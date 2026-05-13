import json

from backend.app.db.mappers import graph_community_from_row
from backend.app.db.records import GraphCommunityRecord


class GraphCommunityRepositoryMixin:
    def upsert_graph_community(self, community: GraphCommunityRecord) -> GraphCommunityRecord:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO graph_community (
                  id, repo_id, name, level, node_ids_json, summary, summary_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  level = excluded.level,
                  node_ids_json = excluded.node_ids_json,
                  summary = excluded.summary,
                  summary_hash = excluded.summary_hash
                """,
                (
                    community.id,
                    community.repo_id,
                    community.name,
                    community.level,
                    json.dumps(community.node_ids, sort_keys=True),
                    community.summary,
                    community.summary_hash,
                ),
            )
        return community

    def replace_graph_communities(
        self,
        repo_id: str,
        communities: list[GraphCommunityRecord],
    ) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM graph_community WHERE repo_id = ?", (repo_id,))
            connection.executemany(
                """
                INSERT INTO graph_community (
                  id, repo_id, name, level, node_ids_json, summary, summary_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        community.id,
                        community.repo_id,
                        community.name,
                        community.level,
                        json.dumps(community.node_ids, sort_keys=True),
                        community.summary,
                        community.summary_hash,
                    )
                    for community in communities
                ],
            )

    def list_graph_communities(self, repo_id: str) -> list[GraphCommunityRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, repo_id, name, level, node_ids_json, summary, summary_hash, created_at
                FROM graph_community
                WHERE repo_id = ?
                ORDER BY level, name
                """,
                (repo_id,),
            ).fetchall()
        return [graph_community_from_row(row) for row in rows]
