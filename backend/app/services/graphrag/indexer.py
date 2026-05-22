from backend.app.config import Settings, get_settings
from backend.app.database import CodeChunkRecord, SQLiteStore
from backend.app.services.async_tasks import run_blocking
from backend.app.services.chunk_builder import ChunkBuilder
from backend.app.services.embedding_index import EmbeddingIndex
from backend.app.services.graph import CodeGraphNode
from backend.app.services.graphrag.models import GraphRAGBuildResult
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.source_file_cache import SourceFileContentProvider


async def build_index(
    store: SQLiteStore,
    repo_id: str,
    *,
    include_embeddings: bool = False,
    llm: LLMGateway | None = None,
    settings: Settings | None = None,
) -> GraphRAGBuildResult:
    repo = store.get_repo(repo_id)
    if repo is None:
        raise ValueError(f"Repository not found: {repo_id}")

    nodes, _edges = store.get_graph(repo_id)
    if not nodes:
        return GraphRAGBuildResult(repo_id=repo_id, status="empty_graph", chunk_count=0)

    chunks = await run_blocking(_build_and_store_source_chunks, store, repo_id, repo.path, nodes)

    embedding_count = 0
    embedding_model: str | None = None
    if include_embeddings and chunks:
        llm = llm or LLMGateway(settings or get_settings())
        result = await EmbeddingIndex(store, llm).build(repo_id, chunks)
        embedding_count = result.count
        embedding_model = result.model

    return GraphRAGBuildResult(
        repo_id=repo_id,
        status="built",
        chunk_count=len(chunks),
        embedding_count=embedding_count,
        embedding_model=embedding_model,
    )


def _build_and_store_source_chunks(
    store: SQLiteStore,
    repo_id: str,
    repo_path: str,
    nodes: list[CodeGraphNode],
) -> list[CodeChunkRecord]:
    chunks = ChunkBuilder().build_source_chunks(
        repo_id=repo_id,
        repo_path=repo_path,
        nodes=nodes,
        content_provider=SourceFileContentProvider(repo_path),
    )
    store.sync_code_chunks(repo_id, chunks)
    return chunks
