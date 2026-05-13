from pathlib import Path


def git_metadata(repo_path: Path) -> tuple[str | None, str | None]:
    git_dir = repo_path / ".git"
    if not git_dir.is_dir():
        return None, None
    return git_origin_url(git_dir), git_head_commit(git_dir)


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
