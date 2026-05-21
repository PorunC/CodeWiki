import hashlib
from pathlib import Path

from backend.app.database import CodeChunkRecord
from backend.app.services.graph import CodeGraphNode
from backend.app.services.graphrag.constants import SOURCE_NODE_TYPES
from backend.app.services.graphrag.utils import estimate_tokens, stable_id
from backend.app.services.source_file_cache import SourceFileContentProvider

CHUNK_SOURCE_NODE_TYPES = SOURCE_NODE_TYPES - {"file"}


class ChunkBuilder:
    def build_source_chunks(
        self,
        *,
        repo_id: str,
        repo_path: str,
        nodes: list[CodeGraphNode],
        content_provider: SourceFileContentProvider | None = None,
    ) -> list[CodeChunkRecord]:
        root = Path(repo_path).resolve()
        provider = content_provider or SourceFileContentProvider(root)
        line_cache: dict[str, list[str]] = {}
        chunks: list[CodeChunkRecord] = []
        seen: set[tuple[str, int, int, str]] = set()

        for node in sorted(nodes, key=lambda item: item.type == "file"):
            if node.type not in CHUNK_SOURCE_NODE_TYPES or not node.file_path:
                continue
            lines = line_cache.get(node.file_path)
            if lines is None:
                file_path = (root / node.file_path).resolve()
                if not file_path.is_file() or not file_path.is_relative_to(root):
                    line_cache[node.file_path] = []
                    continue
                lines = provider.read_lines(file_path)
                line_cache[node.file_path] = lines
            if not lines:
                continue

            start_line = node.start_line or 1
            end_line = node.end_line or start_line
            start_line = max(1, min(start_line, len(lines)))
            end_line = max(start_line, min(end_line, len(lines)))
            content = "\n".join(lines[start_line - 1 : end_line])
            if not content.strip():
                continue
            content = f"{content}\n"
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            dedupe_key = (node.file_path, start_line, end_line, content_hash)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            chunk_id = source_chunk_id(repo_id, node.id, node.file_path, start_line, end_line, content_hash)
            chunks.append(
                CodeChunkRecord(
                    id=chunk_id,
                    repo_id=repo_id,
                    node_id=node.id,
                    file_path=node.file_path,
                    start_line=start_line,
                    end_line=end_line,
                    content=content,
                    content_hash=content_hash,
                    token_count=estimate_tokens(content),
                )
            )
        return sorted(chunks, key=lambda chunk: (chunk.file_path, chunk.start_line, chunk.end_line))


def build_source_chunks(
    *,
    repo_id: str,
    repo_path: str,
    nodes: list[CodeGraphNode],
    content_provider: SourceFileContentProvider | None = None,
) -> list[CodeChunkRecord]:
    return ChunkBuilder().build_source_chunks(
        repo_id=repo_id,
        repo_path=repo_path,
        nodes=nodes,
        content_provider=content_provider,
    )


def source_chunk_id(
    repo_id: str,
    node_id: str,
    file_path: str,
    start_line: int,
    end_line: int,
    content_hash: str,
) -> str:
    return stable_id(repo_id, "chunk", node_id, file_path, str(start_line), str(end_line), content_hash)
