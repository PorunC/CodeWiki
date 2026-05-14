import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.db.utils import now_iso
from backend.app.services.repo_scanner import RepoDescriptor

REPO_METADATA_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RepoAnalysisMetadata:
    repo_id: str
    repo_path: str
    source_type: str
    git_url: str | None
    commit_hash: str | None
    analyzed_at: str
    schema_version: int = REPO_METADATA_SCHEMA_VERSION


def repo_metadata_path(repo_id: str, settings: Settings | None = None) -> Path:
    resolved_settings = settings or get_settings()
    return resolved_settings.storage_dir / "repos" / repo_id / "metadata.json"


def read_repo_metadata(
    repo_id: str,
    *,
    settings: Settings | None = None,
) -> RepoAnalysisMetadata | None:
    path = repo_metadata_path(repo_id, settings)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != REPO_METADATA_SCHEMA_VERSION:
        return None
    return _metadata_from_payload(payload)


def write_repo_metadata(
    repo: RepoDescriptor,
    *,
    settings: Settings | None = None,
) -> RepoAnalysisMetadata:
    metadata = RepoAnalysisMetadata(
        repo_id=repo.id,
        repo_path=repo.path,
        source_type=repo.source_type,
        git_url=repo.git_url,
        commit_hash=repo.commit_hash,
        analyzed_at=now_iso(),
    )
    path = repo_metadata_path(repo.id, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(asdict(metadata), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)
    return metadata


def _metadata_from_payload(payload: dict[str, Any]) -> RepoAnalysisMetadata:
    return RepoAnalysisMetadata(
        repo_id=str(payload.get("repo_id") or ""),
        repo_path=str(payload.get("repo_path") or ""),
        source_type=str(payload.get("source_type") or "local"),
        git_url=_optional_string(payload.get("git_url")),
        commit_hash=_optional_string(payload.get("commit_hash")),
        analyzed_at=str(payload.get("analyzed_at") or ""),
        schema_version=REPO_METADATA_SCHEMA_VERSION,
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
