import json

from backend.app.db.mappers import code_chunk_from_row, graph_community_from_row
from backend.app.db.records import CodeChunkRecord, GraphCommunityRecord


class GraphRAGRepositoryMixin:
    def replace_code_chunks(self, repo_id: str, chunks: list[CodeChunkRecord]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM code_chunk WHERE repo_id = ?", (repo_id,))
            connection.executemany(
                """
                INSERT INTO code_chunk (
                  id, repo_id, node_id, file_path, start_line, end_line,
                  content, content_hash, token_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.repo_id,
                        chunk.node_id,
                        chunk.file_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content,
                        chunk.content_hash,
                        chunk.token_count,
                    )
                    for chunk in chunks
                ],
            )

    def list_code_chunks(self, repo_id: str) -> list[CodeChunkRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, repo_id, node_id, file_path, start_line, end_line,
                       content, content_hash, token_count
                FROM code_chunk
                WHERE repo_id = ?
                ORDER BY file_path, start_line, end_line
                """,
                (repo_id,),
            ).fetchall()
        return [code_chunk_from_row(row) for row in rows]

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

