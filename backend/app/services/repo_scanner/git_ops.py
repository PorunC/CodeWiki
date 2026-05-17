import subprocess
from pathlib import Path

from backend.app.services.repo_scanner.git import git_file_commit_times, git_metadata


class GitOperations:
    def metadata(self, repo_path: Path) -> tuple[str | None, str | None]:
        return git_metadata(repo_path)

    def file_commit_times(self, repo_path: Path, file_paths: list[str]) -> dict[str, str]:
        return git_file_commit_times(repo_path, file_paths)

    def clone(self, git_url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["git", "clone", git_url, str(destination)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ValueError("Cannot clone Git URL because the git executable was not found.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            message = f"Failed to clone Git URL {git_url!r}"
            if detail:
                message = f"{message}: {detail}"
            raise ValueError(message) from exc
        return destination.resolve()
