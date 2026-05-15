from sqlalchemy import delete, select

from backend.app.db.mappers import edge_from_row, node_from_row
from backend.app.models import CodeEdgeRecord, CodeNodeRecord
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode


class CodeGraphRepositoryMixin:
    def replace_graph(
        self,
        repo_id: str,
        *,
        nodes: list[CodeGraphNode],
        edges: list[CodeGraphEdge],
    ) -> None:
        keep_ids = {node.id for node in nodes}
        with self.orm_session() as session:
            session.execute(delete(CodeEdgeRecord).where(CodeEdgeRecord.repo_id == repo_id))
            if keep_ids:
                session.execute(
                    delete(CodeNodeRecord).where(
                        CodeNodeRecord.repo_id == repo_id,
                        CodeNodeRecord.id.not_in(keep_ids),
                    )
                )
            else:
                session.execute(delete(CodeNodeRecord).where(CodeNodeRecord.repo_id == repo_id))

            existing_nodes = {
                record.id: record
                for record in session.scalars(
                    select(CodeNodeRecord).where(CodeNodeRecord.repo_id == repo_id)
                )
            }
            for node in nodes:
                record = existing_nodes.get(node.id)
                if record is None:
                    session.add(_node_record(node))
                    continue
                record.repo_id = node.repo_id
                record.type = node.type
                record.name = node.name
                record.file_path = node.file_path
                record.start_line = node.start_line
                record.end_line = node.end_line
                record.language = node.language
                record.symbol_id = node.symbol_id
                record.summary = node.summary
                record.hash = node.hash
                record.metadata_json = node.metadata

            session.flush()
            session.add_all(_edge_record(edge) for edge in edges)

    def get_graph(self, repo_id: str) -> tuple[list[CodeGraphNode], list[CodeGraphEdge]]:
        with self.orm_session() as session:
            node_rows = session.scalars(
                select(CodeNodeRecord)
                .where(CodeNodeRecord.repo_id == repo_id)
                .order_by(CodeNodeRecord.type, CodeNodeRecord.file_path, CodeNodeRecord.name)
            ).all()
            edge_rows = session.scalars(
                select(CodeEdgeRecord)
                .where(CodeEdgeRecord.repo_id == repo_id)
                .order_by(CodeEdgeRecord.type, CodeEdgeRecord.source_id, CodeEdgeRecord.target_id)
            ).all()
        return (
            [node_from_row(row.as_record_dict()) for row in node_rows],
            [edge_from_row(row.as_record_dict()) for row in edge_rows],
        )


def _node_record(node: CodeGraphNode) -> CodeNodeRecord:
    return CodeNodeRecord(
        id=node.id,
        repo_id=node.repo_id,
        type=node.type,
        name=node.name,
        file_path=node.file_path,
        start_line=node.start_line,
        end_line=node.end_line,
        language=node.language,
        symbol_id=node.symbol_id,
        summary=node.summary,
        hash=node.hash,
        metadata_json=node.metadata,
    )


def _edge_record(edge: CodeGraphEdge) -> CodeEdgeRecord:
    return CodeEdgeRecord(
        id=edge.id,
        repo_id=edge.repo_id,
        source_id=edge.source_id,
        target_id=edge.target_id,
        type=edge.type,
        confidence=edge.confidence,
        weight=edge.weight,
        is_inferred=edge.is_inferred,
        metadata_json=edge.metadata,
    )
