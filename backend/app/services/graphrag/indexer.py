from backend.app.config import Settings, get_settings
from backend.app.database import SQLiteStore
from backend.app.services.graphrag.chunking import build_source_chunks
from backend.app.services.graphrag.embedding import embed_chunks
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

    chunks = build_source_chunks(repo_id=repo_id, repo_path=repo.path, nodes=nodes)
    store.replace_code_chunks(repo_id, chunks)

    embedding_count = 0
    embedding_model: str | None = None
    if include_embeddings and chunks:
        llm = llm or LLMGateway(settings or get_settings())
        embedding_count, embedding_model = await embed_chunks(store, llm, repo_id, chunks)

    return GraphRAGBuildResult(
        repo_id=repo_id,
        status="built",
        chunk_count=len(chunks),
        embedding_count=embedding_count,
        embedding_model=embedding_model,
    )
