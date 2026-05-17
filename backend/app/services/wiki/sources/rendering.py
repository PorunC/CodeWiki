import re
from typing import Any, Protocol

from backend.app.services.wiki.sources.urls import _source_file_href, _source_ref_href

DIAGRAM_SLOT_RE = re.compile(r"^\s*\[\[DIAGRAM:(?P<slot>[a-zA-Z0-9_-]+)\]\]\s*$", re.MULTILINE)
DIAGRAM_HEADING_CANDIDATES = {
    "component": ("## System Context", "## Architecture", "## Core Components", "## Overview"),
    "data_flow": ("## Control Flow", "## Core Workflows", "## System Context"),
    "symbol_flow": ("## Control Flow", "## Core Workflows", "## API Surface", "## System Context"),
    "sequence": ("## Control Flow", "## Core Workflows", "## API Surface"),
    "data_model": ("## Data Model", "## Core Components", "## System Context"),
    "surface": ("## API Surface", "## Frontend Flow", "## Core Components"),
}


class _DiagramLike(Protocol):
    slot: str
    kind: str
    title: str
    heading_hint: str
    reason: str
    lines: list[str]


def _compose_page_markdown(
    markdown: str,
    mermaid: str | list[_DiagramLike],
    source_refs: list[dict[str, Any]],
) -> str:
    diagrams = _normalize_diagrams(mermaid)
    body = _strip_inline_sources_lines(markdown.strip())
    body = _insert_relevant_source_files(body, source_refs)
    body = _place_diagrams(body, diagrams, source_refs)
    sections = [body]
    sections.append(_sources_markdown(source_refs))
    return "\n\n".join(section for section in sections if section)


def _validate_diagram_placeholders(markdown: str, available_slots: set[str]) -> list[str]:
    unknown = sorted(
        {
            match.group("slot")
            for match in DIAGRAM_SLOT_RE.finditer(markdown)
            if match.group("slot") not in available_slots
        }
    )
    if not unknown:
        return []
    return [f"markdown contains unknown diagram placeholders: {', '.join(unknown)}."]


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
    for file_path, refs in _group_source_refs(source_refs):
        file_href = _source_file_href(refs[0])
        file_label = f"[{file_path}]({file_href})" if file_href != "source-link" else file_path
        lines.append(f"- {file_label}")
        for ref in refs:
            prefix = f"{ref['citation_id']} " if isinstance(ref.get("citation_id"), str) else ""
            lines.append(f"  - {prefix}[L{ref['start_line']}-L{ref['end_line']}]({_source_ref_href(ref)})")
    return "\n".join(lines)


def _normalize_diagrams(mermaid: str | list[_DiagramLike]) -> list[_DiagramLike]:
    if isinstance(mermaid, str):
        stripped = mermaid.strip()
        if not stripped:
            return []
        return [
            _StandaloneDiagram(
                slot="graph",
                kind="component",
                title="Graph",
                heading_hint="System Context",
                reason="Generated from validated graph facts.",
                lines=stripped.splitlines(),
            )
        ]
    return mermaid


def _place_diagrams(
    markdown: str,
    diagrams: list[_DiagramLike],
    source_refs: list[dict[str, Any]],
) -> str:
    if not diagrams:
        return _strip_unknown_diagram_slots(markdown)

    by_slot = {diagram.slot: diagram for diagram in diagrams}
    used_slots: set[str] = set()

    def replace_slot(match: re.Match[str]) -> str:
        slot = match.group("slot")
        diagram = by_slot.get(slot)
        if diagram is None:
            return ""
        used_slots.add(slot)
        return _diagram_markdown(diagram, source_refs)

    placed = DIAGRAM_SLOT_RE.sub(replace_slot, markdown)
    unused_diagrams = [diagram for diagram in diagrams if diagram.slot not in used_slots]
    placed = _insert_unused_diagrams(placed, unused_diagrams, source_refs)
    return _strip_unknown_diagram_slots(placed)


def _insert_unused_diagrams(
    markdown: str,
    diagrams: list[_DiagramLike],
    source_refs: list[dict[str, Any]],
) -> str:
    grouped: dict[str | None, list[_DiagramLike]] = {}
    group_order: list[str | None] = []
    for diagram in diagrams:
        heading = _heading_for_diagram(markdown, diagram)
        if heading not in grouped:
            grouped[heading] = []
            group_order.append(heading)
        grouped[heading].append(diagram)

    next_markdown = markdown
    for heading in group_order:
        diagram_markdown = "\n\n".join(
            _diagram_markdown(diagram, source_refs)
            for diagram in grouped[heading]
        )
        if heading is None:
            next_markdown = "\n\n".join(
                section for section in [next_markdown.strip(), diagram_markdown] if section
            )
            continue
        next_markdown, inserted = _insert_after_heading(next_markdown, heading, diagram_markdown)
        if not inserted:
            next_markdown = "\n\n".join(
                section for section in [next_markdown.strip(), diagram_markdown] if section
            )
    return next_markdown


def _heading_for_diagram(markdown: str, diagram: _DiagramLike) -> str | None:
    candidates = (
        f"## {diagram.heading_hint}",
        *DIAGRAM_HEADING_CANDIDATES.get(diagram.kind, ()),
        "## Purpose and Scope",
    )
    for heading in candidates:
        if _has_heading(markdown, heading):
            return heading
    return None


def _has_heading(markdown: str, heading: str) -> bool:
    return any(line.strip() == heading for line in markdown.splitlines())


def _insert_after_heading(markdown: str, heading: str, insertion: str) -> tuple[str, bool]:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != heading:
            continue
        insert_at = index + 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
        next_lines = [*lines[:insert_at], "", insertion, "", *lines[insert_at:]]
        return "\n".join(next_lines).strip(), True
    return markdown, False


def _diagram_markdown(diagram: _DiagramLike, source_refs: list[dict[str, Any]]) -> str:
    lines = [f"### {diagram.title}", "", "```mermaid", *diagram.lines, "```"]
    if diagram.reason:
        lines.extend(["", f"Diagram rationale: {diagram.reason}"])
    return "\n".join(lines)


def _group_source_refs(source_refs: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for ref in source_refs:
        file_path = str(ref.get("file_path") or "")
        if not file_path:
            continue
        if file_path not in grouped:
            grouped[file_path] = []
            order.append(file_path)
        grouped[file_path].append(ref)
    for refs in grouped.values():
        refs.sort(key=lambda ref: (int(ref.get("start_line") or 0), int(ref.get("end_line") or 0)))
    return [(file_path, grouped[file_path]) for file_path in order]


def _strip_inline_sources_lines(markdown: str) -> str:
    lines = markdown.splitlines()
    kept: list[str] = []
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            kept.append(line)
            continue
        if not in_fence and _is_inline_sources_line(line):
            continue
        kept.append(line)
    return _collapse_blank_lines("\n".join(kept)).strip()


def _is_inline_sources_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    stripped = stripped.removeprefix("> ").strip()
    return bool(
        re.match(r"^(?:\*\*)?sources?(?:\*\*)?:\s+\S", stripped, flags=re.IGNORECASE)
        or re.match(r"^\*\*sources?:\*\*\s+\S", stripped, flags=re.IGNORECASE)
    )


def _collapse_blank_lines(markdown: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", markdown)


def _strip_unknown_diagram_slots(markdown: str) -> str:
    return DIAGRAM_SLOT_RE.sub("", markdown).strip()


class _StandaloneDiagram:
    def __init__(
        self,
        *,
        slot: str,
        kind: str,
        title: str,
        heading_hint: str,
        reason: str,
        lines: list[str],
    ) -> None:
        self.slot = slot
        self.kind = kind
        self.title = title
        self.heading_hint = heading_hint
        self.reason = reason
        self.lines = lines


def _draft_markdown(title: str, errors: list[str]) -> str:
    lines = [
        f"# {title}",
        "",
        "This page was not promoted because generation or validation failed.",
        "",
        "## Validation Errors",
    ]
    lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)
