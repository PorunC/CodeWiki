from dataclasses import dataclass


@dataclass(frozen=True)
class CommunityNamingResult:
    repo_id: str
    status: str
    renamed_count: int
    community_count: int
    llm_run_id: str | None = None
    llm_run_ids: list[str] | None = None
    errors: list[str] | None = None
