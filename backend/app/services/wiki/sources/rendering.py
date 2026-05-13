from typing import Any

from backend.app.services.wiki.sources.urls import _source_file_href, _source_ref_href, _source_ref_label


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
