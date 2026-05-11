from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepoDescriptor:
    id: str
    name: str
    path: str
    source_type: str


class RepoScanner:
    def describe(self, path: str, *, name: str | None = None, source_type: str = "local") -> RepoDescriptor:
        repo_path = Path(path).expanduser().resolve()
        return RepoDescriptor(
            id=str(abs(hash(str(repo_path)))),
            name=name or repo_path.name,
            path=str(repo_path),
            source_type=source_type,
        )

