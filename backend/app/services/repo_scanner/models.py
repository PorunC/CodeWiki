from dataclasses import dataclass


@dataclass(frozen=True)
class RepoDescriptor:
    id: str
    name: str
    path: str
    source_type: str
    git_url: str | None = None
    commit_hash: str | None = None


@dataclass(frozen=True)
class RepoFile:
    path: str
    absolute_path: str
    language: str
    is_source: bool
    size_bytes: int
    modified_at: str


@dataclass(frozen=True)
class ScannedFile(RepoFile):
    sha256: str
    last_commit_at: str | None = None


@dataclass(frozen=True)
class RepoFileScanResult:
    repo: RepoDescriptor
    files: list[RepoFile]
    scanned_count: int
    ignored_count: int
    skipped_count: int


@dataclass(frozen=True)
class RepoScanResult:
    repo: RepoDescriptor
    files: list[ScannedFile]
    scanned_count: int
    ignored_count: int
    skipped_count: int
