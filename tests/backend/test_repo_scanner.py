from pathlib import Path

from backend.app.services.repo_scanner import RepoScanner


def test_describe_repo_defaults_name_to_directory() -> None:
    descriptor = RepoScanner().describe(str(Path.cwd()))

    assert descriptor.name == Path.cwd().name
    assert descriptor.source_type == "local"

