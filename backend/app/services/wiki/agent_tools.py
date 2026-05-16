from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_READFILE_REFS = 14
MAX_READFILE_CHARS = 32000


@dataclass(frozen=True)
class ReadFileEvidence:
    reads: list[dict[str, object]]
    source_refs: list[dict[str, Any]]

    def as_payload(self) -> dict[str, object]:
        return {
            "tool": "ReadFile",
            "required": True,
            "description": (
                "Server-executed ReadFile evidence. Treat this as mandatory source material "
                "for the GATHER phase and cite it through allowed_source_refs."
            ),
            "reads": self.reads,
            "recorded_source_refs": self.source_refs,
        }


def readfile_evidence_for_page(
    *,
    repo_path: str,
    allowed_source_refs: list[dict[str, object]],
    source_hints: list[str],
) -> ReadFileEvidence:
    repo_root = Path(repo_path).resolve()
    ordered_refs = _prioritize_refs(allowed_source_refs, source_hints)
    reads: list[dict[str, object]] = []
    source_refs: list[dict[str, Any]] = []
    total_chars = 0
    seen: set[tuple[str, int, int]] = set()

    for ref in ordered_refs:
        file_path = ref.get("file_path")
        start_line = ref.get("start_line")
        end_line = ref.get("end_line")
        if not isinstance(file_path, str) or not isinstance(start_line, int) or not isinstance(end_line, int):
            continue
        key = (file_path, start_line, end_line)
        if key in seen:
            continue
        seen.add(key)
        absolute_path = (repo_root / file_path).resolve()
        if not absolute_path.is_file() or not absolute_path.is_relative_to(repo_root):
            continue
        lines = absolute_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            continue
        numbered_content = _numbered_lines(lines, start_line, end_line)
        if reads and total_chars + len(numbered_content) > MAX_READFILE_CHARS:
            break
        total_chars += len(numbered_content)
        reads.append(
            {
                "tool_call": "ReadFile",
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "content": numbered_content,
            }
        )
        source_ref = {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "read_via": "ReadFile",
        }
        for key_name in ("citation_id", "chunk_id"):
            if isinstance(ref.get(key_name), str):
                source_ref[key_name] = ref[key_name]
        source_refs.append(source_ref)
        if len(reads) >= MAX_READFILE_REFS:
            break
    return ReadFileEvidence(reads=reads, source_refs=source_refs)


def _prioritize_refs(
    allowed_source_refs: list[dict[str, object]],
    source_hints: list[str],
) -> list[dict[str, object]]:
    if not source_hints:
        return allowed_source_refs

    hinted: list[dict[str, object]] = []
    other: list[dict[str, object]] = []
    for ref in allowed_source_refs:
        file_path = ref.get("file_path")
        if isinstance(file_path, str) and _matches_source_hint(file_path, source_hints):
            hinted.append(ref)
        else:
            other.append(ref)
    return [*hinted, *other]


def _matches_source_hint(file_path: str, source_hints: list[str]) -> bool:
    normalized = file_path.strip("/")
    return any(
        normalized == hint.strip("/")
        or normalized.startswith(f"{hint.strip('/').rstrip('/')}/")
        for hint in source_hints
        if hint.strip("/")
    )


def _numbered_lines(lines: list[str], start_line: int, end_line: int) -> str:
    width = len(str(end_line))
    return "\n".join(
        f"{line_number:>{width}}: {lines[line_number - 1]}"
        for line_number in range(start_line, end_line + 1)
    )
