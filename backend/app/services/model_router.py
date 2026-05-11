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
        if task_type in {"catalog", "community_summary", "cluster"}:
            return ModelProfile(task_type=task_type, model=self.settings.llm_default_model, max_tokens=4096)
        if task_type == "qa":
            return ModelProfile(task_type=task_type, model=self.settings.llm_default_model, stream=True)
        return ModelProfile(task_type=task_type, model=self.settings.llm_default_model, max_tokens=12000)

