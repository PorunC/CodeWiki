from backend.app.config import Settings, get_settings
from backend.app.database import SQLiteStore
from backend.app.services.chunk_builder import ChunkBuilder
from backend.app.services.embedding_index import EmbeddingIndex
from backend.app.services.graphrag.models import GraphRAGBuildResult
from backend.app.services.llm_gateway import LLMGateway


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

    chunks = ChunkBuilder().build_source_chunks(repo_id=repo_id, repo_path=repo.path, nodes=nodes)
    store.replace_code_chunks(repo_id, chunks)

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
