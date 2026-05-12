import json

from backend.app.db.mappers import edge_from_row, node_from_row
from backend.app.services.graph_builder import CodeGraphEdge, CodeGraphNode


class CodeGraphRepositoryMixin:
    def replace_graph(
        self,
        repo_id: str,
        *,
        nodes: list[CodeGraphNode],
        edges: list[CodeGraphEdge],
    ) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM code_edge WHERE repo_id = ?", (repo_id,))
            connection.execute(
                "CREATE TEMP TABLE IF NOT EXISTS code_node_keep_ids (id TEXT PRIMARY KEY)"
            )
            connection.execute("DELETE FROM code_node_keep_ids")
            connection.executemany(
                "INSERT INTO code_node_keep_ids (id) VALUES (?)",
                [(node.id,) for node in nodes],
            )
            connection.executemany(
                """
                INSERT INTO code_node (
                  id, repo_id, type, name, file_path, start_line, end_line,
                  language, symbol_id, summary, hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  repo_id = excluded.repo_id,
                  type = excluded.type,
                  name = excluded.name,
                  file_path = excluded.file_path,
                  start_line = excluded.start_line,
                  end_line = excluded.end_line,
                  language = excluded.language,
                  symbol_id = excluded.symbol_id,
                  summary = excluded.summary,
                  hash = excluded.hash,
                  metadata_json = excluded.metadata_json
                """,
                [
                    (
                        node.id,
                        node.repo_id,
                        node.type,
                        node.name,
                        node.file_path,
                        node.start_line,
                        node.end_line,
                        node.language,
                        node.symbol_id,
                        node.summary,
                        node.hash,
                        json.dumps(node.metadata, sort_keys=True),
                    )
                    for node in nodes
                ],
            )
            connection.execute(
                """
                DELETE FROM code_node
                WHERE repo_id = ?
                  AND id NOT IN (SELECT id FROM code_node_keep_ids)
                """,
                (repo_id,),
            )
            connection.execute("DELETE FROM code_node_keep_ids")
            connection.executemany(
                """
                INSERT INTO code_edge (
                  id, repo_id, source_id, target_id, type,
                  confidence, weight, is_inferred, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        edge.id,
                        edge.repo_id,
                        edge.source_id,
                        edge.target_id,
                        edge.type,
                        edge.confidence,
                        edge.weight,
                        int(edge.is_inferred),
                        json.dumps(edge.metadata, sort_keys=True),
                    )
                    for edge in edges
                ],
            )

    def get_graph(self, repo_id: str) -> tuple[list[CodeGraphNode], list[CodeGraphEdge]]:
        with self.connect() as connection:
            node_rows = connection.execute(
                """
                SELECT id, repo_id, type, name, file_path, start_line, end_line,
                       language, symbol_id, summary, hash, metadata_json
                FROM code_node
                WHERE repo_id = ?
                ORDER BY type, file_path, name
                """,
                (repo_id,),
            ).fetchall()
            edge_rows = connection.execute(
                """
                SELECT id, repo_id, source_id, target_id, type,
                       confidence, weight, is_inferred, metadata_json
                FROM code_edge
                WHERE repo_id = ?
                ORDER BY type, source_id, target_id
                """,
                (repo_id,),
            ).fetchall()
        return (
            [node_from_row(row) for row in node_rows],
            [edge_from_row(row) for row in edge_rows],
        )
