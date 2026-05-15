from collections.abc import Mapping
from typing import Any

from backend.app.models import (
    AnalysisRunRecord,
    CodeChunkEmbeddingRecord,
    CodeChunkRecord,
    DocCatalogRecord,
    DocPageRecord,
    GraphCommunityRecord,
    LLMRunRecord,
)
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode


def analysis_run_from_row(row: Mapping[str, Any]) -> AnalysisRunRecord:
    return AnalysisRunRecord(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        status=_get(row, "status"),
        started_at=_get(row, "started_at"),
        finished_at=_get(row, "finished_at"),
        error=_get(row, "error"),
        stats=_get(row, "stats", _get(row, "stats_json", {})),
    )


def node_from_row(row: Mapping[str, Any]) -> CodeGraphNode:
    return CodeGraphNode(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        type=_get(row, "type"),
        name=_get(row, "name"),
        file_path=_get(row, "file_path"),
        start_line=_get(row, "start_line"),
        end_line=_get(row, "end_line"),
        language=_get(row, "language"),
        symbol_id=_get(row, "symbol_id"),
        summary=_get(row, "summary"),
        hash=_get(row, "hash"),
        metadata=_get(row, "metadata_json", {}),
    )


def edge_from_row(row: Mapping[str, Any]) -> CodeGraphEdge:
    return CodeGraphEdge(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        source_id=_get(row, "source_id"),
        target_id=_get(row, "target_id"),
        type=_get(row, "type"),
        confidence=_get(row, "confidence"),
        weight=_get(row, "weight"),
        is_inferred=bool(_get(row, "is_inferred")),
        metadata=_get(row, "metadata_json", {}),
    )


def code_chunk_from_row(row: Mapping[str, Any]) -> CodeChunkRecord:
    return CodeChunkRecord(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        node_id=_get(row, "node_id"),
        file_path=_get(row, "file_path"),
        start_line=_get(row, "start_line"),
        end_line=_get(row, "end_line"),
        content=_get(row, "content"),
        content_hash=_get(row, "content_hash"),
        token_count=_get(row, "token_count"),
    )


def code_chunk_embedding_from_row(row: Mapping[str, Any]) -> CodeChunkEmbeddingRecord:
    return CodeChunkEmbeddingRecord(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        chunk_id=_get(row, "chunk_id"),
        model=_get(row, "model"),
        dimensions=_get(row, "dimensions"),
        embedding=[],
        content_hash=_get(row, "content_hash"),
        created_at=_get(row, "created_at"),
    )


def graph_community_from_row(row: Mapping[str, Any]) -> GraphCommunityRecord:
    return GraphCommunityRecord(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        name=_get(row, "name"),
        level=_get(row, "level"),
        node_ids=_get(row, "node_ids", _get(row, "node_ids_json", [])),
        summary=_get(row, "summary"),
        summary_hash=_get(row, "summary_hash"),
        created_at=_get(row, "created_at"),
    )


def doc_catalog_from_row(row: Mapping[str, Any]) -> DocCatalogRecord:
    return DocCatalogRecord(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        title=_get(row, "title"),
        structure=_get(row, "structure", _get(row, "structure_json", {})),
        generated_at=_get(row, "generated_at"),
    )


def doc_page_from_row(row: Mapping[str, Any]) -> DocPageRecord:
    return DocPageRecord(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        slug=_get(row, "slug"),
        title=_get(row, "title"),
        parent_slug=_get(row, "parent_slug"),
        markdown=_get(row, "markdown"),
        source_refs=_get(row, "source_refs", _get(row, "source_refs_json", [])),
        graph_refs=_get(row, "graph_refs", _get(row, "graph_refs_json", [])),
        status=_get(row, "status"),
        updated_at=_get(row, "updated_at"),
    )


def llm_run_from_row(row: Mapping[str, Any]) -> LLMRunRecord:
    return LLMRunRecord(
        id=_get(row, "id"),
        repo_id=_get(row, "repo_id"),
        task_type=_get(row, "task_type"),
        provider=_get(row, "provider"),
        model=_get(row, "model"),
        model_alias=_get(row, "model_alias"),
        prompt_version=_get(row, "prompt_version"),
        input_hash=_get(row, "input_hash"),
        cache_key=_get(row, "cache_key"),
        tokens_in=_get(row, "tokens_in"),
        tokens_out=_get(row, "tokens_out"),
        cost_usd=_get(row, "cost_usd"),
        duration_ms=_get(row, "duration_ms"),
        response_content=_get(row, "response_content"),
        response_usage=_get(row, "response_usage", _get(row, "response_usage_json", {})),
        cached=bool(_get(row, "cached")),
        status=_get(row, "status"),
        error=_get(row, "error"),
        created_at=_get(row, "created_at"),
    )


def model_mapping(model: object, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(model, field) for field in fields}


def _get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return default
