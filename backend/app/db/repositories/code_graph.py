import json
import re
from typing import Any

from sqlalchemy import delete, select, text

from backend.app.db.mappers import edge_from_row, node_from_row
from backend.app.models import CodeEdgeRecord, CodeNodeRecord
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode, CodeGraphNodeSearchHit

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
SQLITE_SAFE_BATCH_SIZE = 500


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
            session.execute(text("DELETE FROM code_node_fts WHERE repo_id = :repo_id"), {"repo_id": repo_id})
            session.execute(delete(CodeEdgeRecord).where(CodeEdgeRecord.repo_id == repo_id))
            session.commit()
            if keep_ids:
                existing_ids = set(
                    session.scalars(
                        select(CodeNodeRecord.id).where(CodeNodeRecord.repo_id == repo_id)
                    )
                )
                stale_ids = existing_ids - keep_ids
                for stale_batch in _chunks(sorted(stale_ids), SQLITE_SAFE_BATCH_SIZE):
                    session.execute(
                        delete(CodeNodeRecord).where(
                            CodeNodeRecord.repo_id == repo_id,
                            CodeNodeRecord.id.in_(stale_batch),
                        )
                    )
                    session.commit()
            else:
                session.execute(delete(CodeNodeRecord).where(CodeNodeRecord.repo_id == repo_id))
                session.commit()

            _upsert_code_nodes(session, nodes)
            _insert_code_edges(session, edges)
            _insert_code_node_fts(session, nodes)

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

    def search_code_nodes(
        self,
        repo_id: str,
        query: str,
        *,
        types: list[str] | None = None,
        languages: list[str] | None = None,
        path_filters: list[str] | None = None,
        name_filters: list[str] | None = None,
        limit: int = 20,
    ) -> list[CodeGraphNodeSearchHit]:
        limit = max(1, min(limit, 200))
        query = query.strip()
        types = [item for item in (types or []) if item]
        languages = [item for item in (languages or []) if item]
        path_filters = [item.lower() for item in (path_filters or []) if item]
        name_filters = [item.lower() for item in (name_filters or []) if item]

        hits = self._search_code_nodes_fts(
            repo_id,
            query,
            types=types,
            languages=languages,
            limit=max(limit * 5, 50),
        )
        if not hits and query:
            hits = self._search_code_nodes_like(
                repo_id,
                query,
                types=types,
                languages=languages,
                limit=max(limit * 5, 50),
            )
        if not query:
            hits = self._search_code_nodes_by_filters(
                repo_id,
                types=types,
                languages=languages,
                limit=max(limit * 5, 50),
            )

        scored = [
            CodeGraphNodeSearchHit(
                node=hit.node,
                score=_score_node_hit(hit.node, query, hit.score),
                reasons=hit.reasons,
            )
            for hit in hits
        ]
        if path_filters:
            scored = [
                hit for hit in scored
                if any(path in hit.node.file_path.lower() for path in path_filters)
            ]
        if name_filters:
            scored = [
                hit for hit in scored
                if any(name in hit.node.name.lower() for name in name_filters)
            ]

        deduped: dict[str, CodeGraphNodeSearchHit] = {}
        for hit in scored:
            current = deduped.get(hit.node.id)
            if current is None or hit.score > current.score:
                deduped[hit.node.id] = hit
        return sorted(
            deduped.values(),
            key=lambda hit: (-hit.score, hit.node.file_path, hit.node.start_line or 0, hit.node.name),
        )[:limit]

    def _search_code_nodes_fts(
        self,
        repo_id: str,
        query: str,
        *,
        types: list[str],
        languages: list[str],
        limit: int,
    ) -> list[CodeGraphNodeSearchHit]:
        fts_query = _node_fts_query(query)
        if not fts_query:
            return []
        where, params = _node_filter_sql(repo_id, types=types, languages=languages)
        with self.orm_session() as session:
            rows = session.execute(
                text(
                    f"""
                    SELECT n.id, n.repo_id, n.type, n.name, n.file_path, n.start_line, n.end_line,
                           n.language, n.symbol_id, n.summary, n.hash, n.metadata_json,
                           bm25(code_node_fts) AS rank
                    FROM code_node_fts
                    JOIN code_node n ON n.id = code_node_fts.id
                    WHERE code_node_fts MATCH :fts_query AND {where}
                    ORDER BY rank
                    LIMIT :limit
                    """
                ),
                {"fts_query": fts_query, **params, "limit": limit},
            ).mappings().all()
        return [
            CodeGraphNodeSearchHit(
                node=_node_from_mapping(row),
                score=max(0.1, 1.0 - index * 0.02),
                reasons=("fts",),
            )
            for index, row in enumerate(rows)
        ]

    def _search_code_nodes_like(
        self,
        repo_id: str,
        query: str,
        *,
        types: list[str],
        languages: list[str],
        limit: int,
    ) -> list[CodeGraphNodeSearchHit]:
        where, params = _node_filter_sql(repo_id, types=types, languages=languages, alias="n")
        pattern = f"%{query}%"
        start_pattern = f"{query}%"
        with self.orm_session() as session:
            rows = session.execute(
                text(
                    f"""
                    SELECT n.id, n.repo_id, n.type, n.name, n.file_path, n.start_line, n.end_line,
                           n.language, n.symbol_id, n.summary, n.hash, n.metadata_json,
                           CASE
                             WHEN lower(n.name) = lower(:query) THEN 1.0
                             WHEN lower(n.name) LIKE lower(:start_pattern) THEN 0.85
                             WHEN lower(n.name) LIKE lower(:pattern) THEN 0.72
                             WHEN lower(n.symbol_id) LIKE lower(:pattern) THEN 0.62
                             WHEN lower(n.file_path) LIKE lower(:pattern) THEN 0.55
                             ELSE 0.4
                           END AS rank
                    FROM code_node n
                    WHERE {where}
                      AND (
                        lower(n.name) LIKE lower(:pattern)
                        OR lower(n.symbol_id) LIKE lower(:pattern)
                        OR lower(n.file_path) LIKE lower(:pattern)
                      )
                    ORDER BY rank DESC, length(n.name), n.file_path
                    LIMIT :limit
                    """
                ),
                {
                    **params,
                    "query": query,
                    "pattern": pattern,
                    "start_pattern": start_pattern,
                    "limit": limit,
                },
            ).mappings().all()
        return [
            CodeGraphNodeSearchHit(
                node=_node_from_mapping(row),
                score=float(row["rank"]),
                reasons=("like",),
            )
            for row in rows
        ]

    def _search_code_nodes_by_filters(
        self,
        repo_id: str,
        *,
        types: list[str],
        languages: list[str],
        limit: int,
    ) -> list[CodeGraphNodeSearchHit]:
        where, params = _node_filter_sql(repo_id, types=types, languages=languages, alias="n")
        with self.orm_session() as session:
            rows = session.execute(
                text(
                    f"""
                    SELECT n.id, n.repo_id, n.type, n.name, n.file_path, n.start_line, n.end_line,
                           n.language, n.symbol_id, n.summary, n.hash, n.metadata_json
                    FROM code_node n
                    WHERE {where}
                    ORDER BY n.type, n.file_path, n.start_line, n.name
                    LIMIT :limit
                    """
                ),
                {**params, "limit": limit},
            ).mappings().all()
        return [
            CodeGraphNodeSearchHit(node=_node_from_mapping(row), score=0.5, reasons=("filter",))
            for row in rows
        ]


def _upsert_code_nodes(session, nodes: list[CodeGraphNode]) -> None:
    if not nodes:
        return
    statement = text(
        """
        INSERT INTO code_node (
          id, repo_id, type, name, file_path, start_line, end_line,
          language, symbol_id, summary, hash, metadata_json
        )
        VALUES (
          :id, :repo_id, :type, :name, :file_path, :start_line, :end_line,
          :language, :symbol_id, :summary, :hash, :metadata_json
        )
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
        """
    )
    for batch in _chunks(nodes, SQLITE_SAFE_BATCH_SIZE):
        session.execute(statement, [_node_mapping(node) for node in batch])
        session.commit()


def _chunks[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _insert_code_edges(session, edges: list[CodeGraphEdge]) -> None:
    if not edges:
        return
    statement = text(
        """
        INSERT OR IGNORE INTO code_edge (
          id, repo_id, source_id, target_id, type, confidence, weight, is_inferred, metadata_json
        )
        VALUES (
          :id, :repo_id, :source_id, :target_id, :type, :confidence, :weight,
          :is_inferred, :metadata_json
        )
        """
    )
    for batch in _chunks(edges, SQLITE_SAFE_BATCH_SIZE):
        session.execute(statement, [_edge_mapping(edge) for edge in batch])
        session.commit()


def _node_mapping(node: CodeGraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "repo_id": node.repo_id,
        "type": node.type,
        "name": node.name,
        "file_path": node.file_path,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "language": node.language,
        "symbol_id": node.symbol_id,
        "summary": node.summary,
        "hash": node.hash,
        "metadata_json": json.dumps(node.metadata, sort_keys=True),
    }


def _edge_mapping(edge: CodeGraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "repo_id": edge.repo_id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "type": edge.type,
        "confidence": edge.confidence,
        "weight": edge.weight,
        "is_inferred": edge.is_inferred,
        "metadata_json": json.dumps(edge.metadata, sort_keys=True),
    }


def _insert_code_node_fts(session, nodes: list[CodeGraphNode]) -> None:
    if not nodes:
        return
    statement = text(
        """
            INSERT OR IGNORE INTO code_node_fts (
              id, repo_id, type, name, file_path, language, symbol_id, summary, signature, docstring
            )
            VALUES (
              :id, :repo_id, :type, :name, :file_path, :language, :symbol_id, :summary,
              :signature, :docstring
            )
        """
    )
    for batch in _chunks(nodes, SQLITE_SAFE_BATCH_SIZE):
        session.execute(statement, [_node_fts_mapping(node) for node in batch])
        session.commit()


def _node_fts_mapping(node: CodeGraphNode) -> dict[str, str]:
    return {
        "id": node.id,
        "repo_id": node.repo_id,
        "type": node.type,
        "name": node.name,
        "file_path": node.file_path,
        "language": node.language or "",
        "symbol_id": node.symbol_id or "",
        "summary": node.summary or "",
        "signature": _metadata_text(node.metadata.get("signature")),
        "docstring": _metadata_text(node.metadata.get("docstring")),
    }


def _metadata_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value if item is not None)
    return str(value)


def _node_fts_query(query: str) -> str:
    query_terms: list[str] = []
    seen: set[str] = set()
    for match in TOKEN_RE.finditer(query):
        term = match.group(0).lower()
        if term in seen:
            continue
        seen.add(term)
        query_terms.append(term)
    return " OR ".join(f'"{term}"*' for term in query_terms[:16])


def _node_filter_sql(
    repo_id: str,
    *,
    types: list[str],
    languages: list[str],
    alias: str = "n",
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {"repo_id": repo_id}
    prefix = f"{alias}." if alias else ""
    clauses = [f"{prefix}repo_id = :repo_id"]
    if types:
        names = []
        for index, node_type in enumerate(types):
            key = f"type_{index}"
            names.append(f":{key}")
            params[key] = node_type
        clauses.append(f"{prefix}type IN ({', '.join(names)})")
    if languages:
        names = []
        for index, language in enumerate(languages):
            key = f"language_{index}"
            names.append(f":{key}")
            params[key] = language
        clauses.append(f"{prefix}language IN ({', '.join(names)})")
    return " AND ".join(clauses), params


def _node_from_mapping(row) -> CodeGraphNode:
    data = dict(row)
    metadata = data.get("metadata_json")
    if isinstance(metadata, str):
        try:
            data["metadata_json"] = json.loads(metadata)
        except json.JSONDecodeError:
            data["metadata_json"] = {}
    return node_from_row(data)


def _score_node_hit(node: CodeGraphNode, query: str, base_score: float) -> float:
    if not query:
        return base_score
    query_lower = query.lower()
    name_lower = node.name.lower()
    score = base_score
    if name_lower == query_lower.replace(" ", "") or name_lower == query_lower:
        score += 2.0
    elif any(term == name_lower for term in TOKEN_RE.findall(query_lower)):
        score += 1.4
    elif name_lower.startswith(query_lower):
        score += 0.9
    elif query_lower in name_lower:
        score += 0.6
    if node.file_path and any(term in node.file_path.lower() for term in TOKEN_RE.findall(query_lower)):
        score += 0.25
    score += {
        "endpoint": 0.35,
        "function": 0.3,
        "method": 0.3,
        "class": 0.28,
        "interface": 0.25,
        "schema": 0.22,
        "file": 0.1,
        "module": -0.15,
    }.get(node.type, 0.0)
    return round(score, 4)
