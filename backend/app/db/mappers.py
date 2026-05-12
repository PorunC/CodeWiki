import json
import sqlite3

from backend.app.db.records import (
    AnalysisRunRecord,
    CodeChunkRecord,
    DocCatalogRecord,
    DocPageRecord,
    GraphCommunityRecord,
    LLMRunRecord,
)
from backend.app.services.graph_builder import CodeGraphEdge, CodeGraphNode


def analysis_run_from_row(row: sqlite3.Row) -> AnalysisRunRecord:
    return AnalysisRunRecord(
        id=row["id"],
        repo_id=row["repo_id"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        stats=json.loads(row["stats_json"] or "{}"),
    )


def node_from_row(row: sqlite3.Row) -> CodeGraphNode:
    return CodeGraphNode(
        id=row["id"],
        repo_id=row["repo_id"],
        type=row["type"],
        name=row["name"],
        file_path=row["file_path"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        language=row["language"],
        symbol_id=row["symbol_id"],
        summary=row["summary"],
        hash=row["hash"],
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def edge_from_row(row: sqlite3.Row) -> CodeGraphEdge:
    return CodeGraphEdge(
        id=row["id"],
        repo_id=row["repo_id"],
        source_id=row["source_id"],
        target_id=row["target_id"],
        type=row["type"],
        confidence=row["confidence"],
        weight=row["weight"],
        is_inferred=bool(row["is_inferred"]),
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def code_chunk_from_row(row: sqlite3.Row) -> CodeChunkRecord:
    return CodeChunkRecord(
        id=row["id"],
        repo_id=row["repo_id"],
        node_id=row["node_id"],
        file_path=row["file_path"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        content=row["content"],
        content_hash=row["content_hash"],
        token_count=row["token_count"],
    )


def graph_community_from_row(row: sqlite3.Row) -> GraphCommunityRecord:
    return GraphCommunityRecord(
        id=row["id"],
        repo_id=row["repo_id"],
        name=row["name"],
        level=row["level"],
        node_ids=json.loads(row["node_ids_json"] or "[]"),
        summary=row["summary"],
        summary_hash=row["summary_hash"],
        created_at=row["created_at"],
    )


def doc_catalog_from_row(row: sqlite3.Row) -> DocCatalogRecord:
    return DocCatalogRecord(
        id=row["id"],
        repo_id=row["repo_id"],
        title=row["title"],
        structure=json.loads(row["structure_json"] or "{}"),
        generated_at=row["generated_at"],
    )


def doc_page_from_row(row: sqlite3.Row) -> DocPageRecord:
    return DocPageRecord(
        id=row["id"],
        repo_id=row["repo_id"],
        slug=row["slug"],
        title=row["title"],
        parent_slug=row["parent_slug"],
        markdown=row["markdown"],
        source_refs=json.loads(row["source_refs_json"] or "[]"),
        graph_refs=json.loads(row["graph_refs_json"] or "[]"),
        status=row["status"],
        updated_at=row["updated_at"],
    )


def llm_run_from_row(row: sqlite3.Row) -> LLMRunRecord:
    return LLMRunRecord(
        id=row["id"],
        repo_id=row["repo_id"],
        task_type=row["task_type"],
        provider=row["provider"],
        model=row["model"],
        model_alias=row["model_alias"],
        prompt_version=row["prompt_version"],
        input_hash=row["input_hash"],
        cache_key=row["cache_key"],
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        cost_usd=row["cost_usd"],
        duration_ms=row["duration_ms"],
        cached=bool(row["cached"]),
        status=row["status"],
        error=row["error"],
        created_at=row["created_at"],
    )

