import subprocess
from pathlib import Path


def git_metadata(repo_path: Path) -> tuple[str | None, str | None]:
    git_dir = repo_path / ".git"
    if not git_dir.is_dir():
        return None, None
    return git_origin_url(git_dir), git_head_commit(git_dir)


def git_file_commit_times(repo_path: Path, file_paths: list[str]) -> dict[str, str]:
    if not file_paths or not (repo_path / ".git").is_dir():
        return {}
    commit_times: dict[str, str] = {}
    unique_paths = sorted(set(file_paths))
    for batch in _batches(unique_paths, 200):
        commit_times.update(_git_file_commit_times_batch(repo_path, batch))
    return commit_times


def git_list_files(repo_path: Path) -> list[str] | None:
    if not (repo_path / ".git").is_dir():
        return None
    try:
        process = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={repo_path}",
                "-C",
                str(repo_path),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if process.returncode != 0:
        return None
    return sorted(
        item.decode("utf-8", errors="replace")
        for item in process.stdout.split(b"\0")
        if item
    )


def git_diff_changed_paths(
    repo_path: Path,
    base_commit: str | None,
    head_commit: str | None,
) -> set[str] | None:
    if not base_commit or not head_commit or not (repo_path / ".git").is_dir():
        return None
    if base_commit == head_commit:
        return set()
    try:
        process = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={repo_path}",
                "-C",
                str(repo_path),
                "diff",
                "--name-status",
                "--find-renames",
                base_commit,
                head_commit,
                "--",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if process.returncode != 0:
        return None
    paths: set[str] = set()
    for raw_line in process.stdout.splitlines():
        parts = raw_line.strip().split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith(("R", "C")) and len(parts) >= 3:
            paths.add(parts[1])
            paths.add(parts[2])
        else:
            paths.add(parts[1])
    return paths


def git_origin_url(git_dir: Path) -> str | None:
    config_path = git_dir / "config"
    if not config_path.is_file():
        return None
    current_section = ""
    for raw_line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line
            continue
        if current_section == '[remote "origin"]' and line.startswith("url"):
            _, _, value = line.partition("=")
            return value.strip() or None
    return None


def git_head_commit(git_dir: Path) -> str | None:
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return None
    head = head_path.read_text(encoding="utf-8", errors="replace").strip()
    if not head:
        return None
    if not head.startswith("ref:"):
        return head
    ref_name = head.removeprefix("ref:").strip()
    ref_path = git_dir / ref_name
    if ref_path.is_file():
        return ref_path.read_text(encoding="utf-8", errors="replace").strip() or None
    packed_refs = git_dir / "packed-refs"
    if packed_refs.is_file():
        for raw_line in packed_refs.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw_line.startswith("#") or not raw_line.strip():
                continue
            commit, _, ref = raw_line.partition(" ")
            if ref.strip() == ref_name:
                return commit.strip() or None
    return None


def _git_file_commit_times_batch(repo_path: Path, file_paths: list[str]) -> dict[str, str]:
    remaining = set(file_paths)
    commit_times: dict[str, str] = {}
    current_timestamp: str | None = None
    try:
        process = subprocess.Popen(
            [
                "git",
                "-c",
                f"safe.directory={repo_path}",
                "-C",
                str(repo_path),
                "log",
                "--format=@@codewiki:%cI",
                "--name-only",
                "--",
                *file_paths,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return {}

    if process.stdout is None:
        _finish_process(process)
        return {}

    try:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if line.startswith("@@codewiki:"):
                current_timestamp = line.removeprefix("@@codewiki:").strip() or None
                continue
            if current_timestamp and line in remaining:
                commit_times[line] = current_timestamp
                remaining.remove(line)
                if not remaining:
                    process.terminate()
                    break
    finally:
        _finish_process(process)
    return commit_times


def _finish_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _batches(items: list[str], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
