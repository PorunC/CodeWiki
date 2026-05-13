import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

CITATION_MARKER_RE = re.compile(r"\[\[(S\d+)\]\]")

def _source_refs_from_chunks(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "citation_id": f"S{index + 1}",
            "file_path": chunk["file_path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "chunk_id": chunk["id"],
        }
        for index, chunk in enumerate(chunks)
        if isinstance(chunk.get("file_path"), str)
        and isinstance(chunk.get("start_line"), int)
        and isinstance(chunk.get("end_line"), int)
    ]


def _validate_source_refs(
    *,
    repo_path: str,
    requested_refs: Any,
    source_chunks: list[dict[str, object]],
    allowed_source_refs: list[dict[str, object]],
    source_url_base: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(requested_refs, list):
        return [], ["source_refs must be an array."]

    repo_root = Path(repo_path).resolve()
    chunk_ranges = _chunk_ranges(source_chunks)
    allowed_by_citation_id = _allowed_refs_by_citation_id(allowed_source_refs)
    valid_refs: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, int, int]] = set()

    for index, raw_ref in enumerate(requested_refs):
        if not isinstance(raw_ref, dict):
            errors.append(f"source_refs[{index}] must be an object.")
            continue
        citation_id = str(raw_ref.get("citation_id") or "").strip()
        if citation_id:
            allowed_ref = allowed_by_citation_id.get(citation_id)
            if allowed_ref is None:
                errors.append(f"source_refs[{index}] uses unknown citation_id: {citation_id}.")
                continue
            file_path = str(allowed_ref.get("file_path") or "").strip()
            start_line = allowed_ref.get("start_line")
            end_line = allowed_ref.get("end_line")
        else:
            file_path = str(raw_ref.get("file_path") or "").strip()
            start_line = raw_ref.get("start_line")
            end_line = raw_ref.get("end_line")
        if not file_path or not isinstance(start_line, int) or not isinstance(end_line, int):
            errors.append(f"source_refs[{index}] must include file_path, start_line, end_line.")
            continue
        if start_line < 1 or end_line < start_line:
            errors.append(f"source_refs[{index}] has invalid line range.")
            continue

        absolute_path = (repo_root / file_path).resolve()
        if not absolute_path.is_file() or not absolute_path.is_relative_to(repo_root):
            errors.append(f"source_refs[{index}] file does not exist in repo: {file_path}.")
            continue

        lines = absolute_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if end_line > len(lines):
            errors.append(f"source_refs[{index}] line range exceeds file length: {file_path}.")
            continue

        content = "\n".join(lines[start_line - 1 : end_line])
        matching_chunk = next(
            (
                chunk
                for chunk in chunk_ranges.get(file_path, [])
                if start_line >= chunk["start_line"]
                and end_line <= chunk["end_line"]
                and content in str(chunk["content"])
            ),
            None,
        )
        if matching_chunk is None:
            errors.append(
                f"source_refs[{index}] is not covered by the retrieved source_chunks: "
                f"{file_path}:{start_line}-{end_line}."
            )
            continue

        key = (file_path, start_line, end_line)
        if key in seen:
            continue
        seen.add(key)
        citation_id = citation_id or _citation_id_for_range(
            allowed_source_refs,
            file_path,
            start_line,
            end_line,
        )
        ref = {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "chunk_id": matching_chunk["id"],
        }
        if citation_id:
            ref["citation_id"] = citation_id
        if source_url_base:
            ref["source_url"] = _source_url(source_url_base, file_path, start_line, end_line)
        valid_refs.append(ref)
    return valid_refs, errors


def _include_markdown_citation_refs(
    markdown: str,
    source_refs: list[dict[str, Any]],
    allowed_source_refs: list[dict[str, object]],
    *,
    source_url_base: str | None = None,
) -> list[dict[str, Any]]:
    refs_by_citation_id = {
        str(ref["citation_id"]): ref
        for ref in source_refs
        if isinstance(ref.get("citation_id"), str)
    }
    allowed_by_citation_id = _allowed_refs_by_citation_id(allowed_source_refs)
    for citation_id in sorted(CITATION_MARKER_RE.findall(markdown), key=_citation_sort_key):
        if citation_id in refs_by_citation_id:
            continue
        allowed = allowed_by_citation_id.get(citation_id)
        if allowed is None:
            continue
        file_path = allowed.get("file_path")
        start_line = allowed.get("start_line")
        end_line = allowed.get("end_line")
        chunk_id = allowed.get("chunk_id")
        if not isinstance(file_path, str) or not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        ref: dict[str, Any] = {
            "citation_id": citation_id,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
        }
        if isinstance(chunk_id, str):
            ref["chunk_id"] = chunk_id
        if source_url_base:
            ref["source_url"] = _source_url(source_url_base, file_path, start_line, end_line)
        refs_by_citation_id[citation_id] = ref
    return list(refs_by_citation_id.values())


def _citation_sort_key(citation_id: str) -> tuple[int, str]:
    suffix = citation_id.removeprefix("S")
    return (int(suffix), citation_id) if suffix.isdigit() else (10**9, citation_id)


def _allowed_refs_by_citation_id(
    allowed_source_refs: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    refs: dict[str, dict[str, object]] = {}
    for ref in allowed_source_refs:
        citation_id = ref.get("citation_id")
        if isinstance(citation_id, str) and citation_id:
            refs[citation_id] = ref
    return refs


def _citation_id_for_range(
    allowed_source_refs: list[dict[str, object]],
    file_path: str,
    start_line: int,
    end_line: int,
) -> str | None:
    for ref in allowed_source_refs:
        if (
            ref.get("file_path") == file_path
            and ref.get("start_line") == start_line
            and ref.get("end_line") == end_line
            and isinstance(ref.get("citation_id"), str)
        ):
            return str(ref["citation_id"])
    return None


def _chunk_ranges(chunks: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    ranges: dict[str, list[dict[str, object]]] = {}
    for chunk in chunks:
        file_path = chunk.get("file_path")
        start_line = chunk.get("start_line")
        end_line = chunk.get("end_line")
        content = chunk.get("content")
        if (
            isinstance(file_path, str)
            and isinstance(start_line, int)
            and isinstance(end_line, int)
            and isinstance(content, str)
        ):
            ranges.setdefault(file_path, []).append(
                {
                    "id": chunk.get("id"),
                    "start_line": start_line,
                    "end_line": end_line,
                    "content": content,
                }
            )
    return ranges


def _validate_citation_markers(markdown: str, source_refs: list[dict[str, Any]]) -> list[str]:
    markers = set(CITATION_MARKER_RE.findall(markdown))
    if not markers:
        return []
    valid_markers = {
        citation_id
        for ref in source_refs
        if isinstance((citation_id := ref.get("citation_id")), str)
    }
    unknown = sorted(markers - valid_markers)
    return [f"markdown contains citation markers not present in source_refs: {', '.join(unknown)}."] if unknown else []


def _strip_unknown_citation_markers(markdown: str, source_refs: list[dict[str, Any]]) -> str:
    valid_markers = {
        citation_id
        for ref in source_refs
        if isinstance((citation_id := ref.get("citation_id")), str)
    }

    def replace_marker(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1) in valid_markers else ""

    return CITATION_MARKER_RE.sub(replace_marker, markdown)


def _filter_unused_source_refs(
    markdown: str,
    source_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    markers = set(CITATION_MARKER_RE.findall(markdown))
    if not markers:
        return source_refs
    return [
        ref
        for ref in source_refs
        if not isinstance(ref.get("citation_id"), str) or ref["citation_id"] in markers
    ]


def _replace_citation_markers(markdown: str, source_refs: list[dict[str, Any]]) -> str:
    refs_by_citation_id = {
        citation_id: ref
        for ref in source_refs
        if isinstance((citation_id := ref.get("citation_id")), str)
    }

    def replace_marker(match: re.Match[str]) -> str:
        citation_id = match.group(1)
        ref = refs_by_citation_id.get(citation_id)
        if ref is None:
            return match.group(0)
        return f"[{_source_ref_label(ref)}]({_source_ref_href(ref)})"

    return CITATION_MARKER_RE.sub(replace_marker, markdown)


def _compose_page_markdown(
    markdown: str,
    mermaid: str,
    source_refs: list[dict[str, Any]],
) -> str:
    sections = [_insert_relevant_source_files(markdown.strip(), source_refs)]
    if mermaid:
        sections.append(mermaid.strip())
    sections.append(_sources_markdown(source_refs))
    return "\n\n".join(section for section in sections if section)


def _insert_relevant_source_files(markdown: str, source_refs: list[dict[str, Any]]) -> str:
    if "## Relevant source files" in markdown:
        return markdown

    relevant = _relevant_source_files_markdown(source_refs)
    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        rest = "\n".join(lines[1:]).strip()
        return "\n\n".join(section for section in [lines[0], relevant, rest] if section)
    return "\n\n".join(section for section in [relevant, markdown] if section)


def _relevant_source_files_markdown(source_refs: list[dict[str, Any]]) -> str:
    lines = ["## Relevant source files"]
    seen: set[str] = set()
    for ref in source_refs:
        file_path = str(ref["file_path"])
        if file_path in seen:
            continue
        seen.add(file_path)
        lines.append(f"- [{file_path}]({_source_file_href(ref)})")
    return "\n".join(lines)


def _sources_markdown(source_refs: list[dict[str, Any]]) -> str:
    lines = ["## Sources"]
    for ref in source_refs:
        href = _source_ref_href(ref)
        prefix = f"{ref['citation_id']} " if isinstance(ref.get("citation_id"), str) else ""
        lines.append(
            f"- {prefix}[{_source_ref_label(ref)}]({href})"
        )
    return "\n".join(lines)


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


def _draft_markdown(title: str, errors: list[str]) -> str:
    lines = [
        f"# {title}",
        "",
        "This page was not promoted because source reference validation failed.",
        "",
        "## Validation Errors",
    ]
    lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


