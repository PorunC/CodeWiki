from dataclasses import replace
from typing import Any

from backend.app.database import SQLiteStore
from backend.app.services.graph_rag import RetrievalTrace

MAX_SOURCE_HINT_CHUNKS = 10
MAX_SOURCE_HINT_CHUNKS_PER_FILE = 3


def _source_hints_from_item(item: dict[str, Any]) -> list[str]:
    hints = item.get("source_hints")
    if not isinstance(hints, list):
        return []
    return [
        hint.strip().strip("/")
        for hint in (str(value) for value in hints)
        if hint.strip().strip("/")
    ][:8]


def _trace_with_source_hint_chunks(
    trace: RetrievalTrace,
    store: SQLiteStore,
    repo_id: str,
    source_hints: list[str],
) -> RetrievalTrace:
    if not source_hints:
        return trace

    hinted_chunks: list[dict[str, object]] = []
    per_file_counts: dict[str, int] = {}
    for chunk in store.list_code_chunks(repo_id):
        if not _matches_source_hint(chunk.file_path, source_hints):
            continue
        if per_file_counts.get(chunk.file_path, 0) >= MAX_SOURCE_HINT_CHUNKS_PER_FILE:
            continue
        per_file_counts[chunk.file_path] = per_file_counts.get(chunk.file_path, 0) + 1
        hinted_chunks.append(
            {
                "id": chunk.id,
                "node_id": chunk.node_id,
                "file_path": chunk.file_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "token_count": chunk.token_count,
                "score": 0.45,
                "reasons": ["source_hint"],
            }
        )
        if len(hinted_chunks) >= MAX_SOURCE_HINT_CHUNKS:
            break

    if not hinted_chunks:
        return trace
    return replace(
        trace,
        source_chunks=_dedupe_source_chunks([*trace.source_chunks, *hinted_chunks]),
    )


def _matches_source_hint(file_path: str, source_hints: list[str]) -> bool:
    normalized = file_path.strip("/")
    return any(normalized == hint or normalized.startswith(f"{hint.rstrip('/')}/") for hint in source_hints)


def _dedupe_source_chunks(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("id") or "")
        key = chunk_id or (
            f"{chunk.get('file_path')}:{chunk.get('start_line')}:{chunk.get('end_line')}"
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
    return deduped
