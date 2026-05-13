from dataclasses import dataclass, field

from backend.app.config import Settings


@dataclass(frozen=True)
class ModelProfile:
    task_type: str
    model: str
    temperature: float = 0.1
    max_tokens: int | None = None
    stream: bool = False
    fallback_models: list[str] = field(default_factory=list)


class ModelRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def profile_for(self, task_type: str) -> ModelProfile:
        if task_type == "embedding":
            return ModelProfile(task_type=task_type, model=self.settings.llm_embedding_model)
        if task_type == "catalog":
            return ModelProfile(task_type=task_type, model=self._catalog_model(), max_tokens=4096)
        if task_type in {"community_summary", "cluster"}:
            return ModelProfile(task_type=task_type, model=self._community_model(), max_tokens=4096)
        if task_type == "page":
            return ModelProfile(task_type=task_type, model=self._page_model(), max_tokens=12000)
        if task_type == "qa":
            return ModelProfile(task_type=task_type, model=self._qa_model(), stream=True)
        return ModelProfile(task_type=task_type, model=self._large_model(), max_tokens=12000)

    def _small_model(self) -> str:
        return self.settings.llm_small_model or self.settings.llm_default_model

    def _large_model(self) -> str:
        return self.settings.llm_large_model or self.settings.llm_default_model

    def _catalog_model(self) -> str:
        return self.settings.llm_catalog_model or self._small_model()

    def _community_model(self) -> str:
        return self.settings.llm_community_model or self._small_model()

    def _page_model(self) -> str:
        return self.settings.llm_page_model or self._large_model()

    def _qa_model(self) -> str:
        return self.settings.llm_qa_model or self._large_model()
