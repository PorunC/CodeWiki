from backend.app.config import get_settings
from backend.app.database import CodeWikiStore
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.question_answerer import QuestionAnswerer
from backend.app.services.wiki import WikiGenerator


def wiki_generator(store: CodeWikiStore) -> WikiGenerator:
    settings = get_settings()
    return WikiGenerator(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
        settings=settings,
    )


def question_answerer(store: CodeWikiStore) -> QuestionAnswerer:
    settings = get_settings()
    return QuestionAnswerer(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
    )
