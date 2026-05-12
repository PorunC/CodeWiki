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
            connection.execute("DELETE FROM code_node WHERE repo_id = ?", (repo_id,))
            connection.executemany(
                """
                INSERT INTO code_node (
                  id, repo_id, type, name, file_path, start_line, end_line,
                  language, symbol_id, summary, hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

