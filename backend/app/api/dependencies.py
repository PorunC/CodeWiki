from functools import cached_property, lru_cache
from typing import Annotated

from fastapi import Depends

from backend.app.config import Settings, get_settings
from backend.app.database import CodeWikiStore, get_store
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.llm.gateway import LLMGateway
from backend.app.services.wiki import WikiGenerator


class ServiceContainer:
    def __init__(self, *, settings: Settings, store: CodeWikiStore) -> None:
        self.settings = settings
        self.store = store

    @cached_property
    def llm_gateway(self) -> LLMGateway:
        return LLMGateway(self.settings)

    @cached_property
    def graph_retriever(self) -> GraphRAGRetriever:
        return GraphRAGRetriever(store=self.store, settings=self.settings)

    @cached_property
    def wiki_generator(self) -> WikiGenerator:
        return WikiGenerator(
            self.graph_retriever,
            self.llm_gateway,
            store=self.store,
            settings=self.settings,
        )

    @cached_property
    def incremental_updater(self) -> IncrementalUpdater:
        return IncrementalUpdater(
            store=self.store,
            graphrag=self.graph_retriever,
        )


@lru_cache
def get_service_container() -> ServiceContainer:
    return ServiceContainer(settings=get_settings(), store=get_store())


def get_store_dependency() -> CodeWikiStore:
    return get_service_container().store


def get_wiki_generator() -> WikiGenerator:
    return get_service_container().wiki_generator


def get_incremental_updater() -> IncrementalUpdater:
    return get_service_container().incremental_updater


StoreDep = Annotated[CodeWikiStore, Depends(get_store_dependency)]
WikiGeneratorDep = Annotated[WikiGenerator, Depends(get_wiki_generator)]
IncrementalUpdaterDep = Annotated[IncrementalUpdater, Depends(get_incremental_updater)]
