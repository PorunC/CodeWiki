import re
from typing import Any
from urllib.parse import quote


def _source_ref_label(ref: dict[str, Any]) -> str:
    return f"{ref['file_path']}:L{ref['start_line']}-L{ref['end_line']}"


def _source_ref_href(ref: dict[str, Any]) -> str:
    source_url = ref.get("source_url")
    return source_url if isinstance(source_url, str) and source_url else "source-link"


def _source_file_href(ref: dict[str, Any]) -> str:
    source_url = ref.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        return "source-link"
    return re.sub(r"#L\d+(?:-L\d+)?$", "", source_url)


def _source_url_base(git_url: str | None, commit_hash: str | None) -> str | None:
    if not git_url:
        return None
    normalized = git_url.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized.removesuffix(".git")
    if normalized.startswith("git@"):
        host_and_path = normalized.removeprefix("git@")
        host, _, repo_path = host_and_path.partition(":")
        if host and repo_path:
            normalized = f"https://{host}/{repo_path}"
    ref = commit_hash or "HEAD"
    if "gitlab" in normalized:
        return f"{normalized}/-/blob/{ref}"
    if "bitbucket.org" in normalized:
        return f"{normalized}/src/{ref}"
    return f"{normalized}/blob/{ref}"


def _source_url(source_url_base: str, file_path: str, start_line: int, end_line: int) -> str:
    return f"{source_url_base}/{quote(file_path, safe='/')}#L{start_line}-L{end_line}"
