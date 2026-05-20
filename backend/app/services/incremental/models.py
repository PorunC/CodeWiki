from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IncrementalUpdatePlan:
    repo_id: str
    changed_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    unchanged_files: list[str] = field(default_factory=list)
    detection_strategy: str = "sha256"
    base_commit: str | None = None
    head_commit: str | None = None

    @property
    def affected_files(self) -> list[str]:
        return sorted({*self.changed_files, *self.new_files, *self.deleted_files})

    def as_dict(self) -> dict[str, object]:
        return {
            "repo_id": self.repo_id,
            "changed_files": self.changed_files,
            "new_files": self.new_files,
            "deleted_files": self.deleted_files,
            "unchanged_files": self.unchanged_files,
            "affected_files": self.affected_files,
            "detection_strategy": self.detection_strategy,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
        }


@dataclass(frozen=True)
class IncrementalUpdateResult:
    run_id: str
    repo_id: str
    status: str
    plan: IncrementalUpdatePlan
    scanned_count: int
    parsed_file_count: int
    reused_file_count: int
    node_count: int
    edge_count: int
    community_count: int
    chunk_count: int
    community_count_by_level: dict[str, int] = field(default_factory=dict)
    stale_pages: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def stats(self) -> dict[str, Any]:
        return {
            "mode": "incremental",
            "plan": self.plan.as_dict(),
            "scanned_count": self.scanned_count,
            "parsed_file_count": self.parsed_file_count,
            "reused_file_count": self.reused_file_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "community_count": self.community_count,
            "community_count_by_level": self.community_count_by_level,
            "chunk_count": self.chunk_count,
            "stale_pages": self.stale_pages,
            "errors": self.errors,
        }
