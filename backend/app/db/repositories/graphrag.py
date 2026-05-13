from backend.app.db.repositories.code_chunks import CodeChunkRepositoryMixin
from backend.app.db.repositories.communities import GraphCommunityRepositoryMixin
from backend.app.db.repositories.embeddings import CodeChunkEmbeddingRepositoryMixin


class GraphRAGRepositoryMixin(
    CodeChunkRepositoryMixin,
    CodeChunkEmbeddingRepositoryMixin,
    GraphCommunityRepositoryMixin,
):
    """Compatibility mixin composed from the focused GraphRAG repositories."""
