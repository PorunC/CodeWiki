from dataclasses import dataclass
from typing import Any

from backend.app.services.graphrag import RetrievalTrace
from backend.app.services.repo_scanner import RepoDescriptor
from backend.app.services.wiki.markdown import _strip_llm_mermaid, _validate_page_markdown
from backend.app.services.wiki.sources import (
    _filter_unused_source_refs,
    _include_markdown_citation_refs,
    _source_url,
    _source_url_base,
    _strip_unknown_citation_markers,
    _validate_citation_markers,
    _validate_diagram_placeholders,
    _validate_source_refs,
)


@dataclass(frozen=True)
class PageValidationResult:
    markdown: str
    source_refs: list[dict[str, Any]]
    errors: list[str]


class PageResponseValidator:
    def validate(
        self,
        *,
        repo: RepoDescriptor,
        payload: dict[str, Any],
        title: str,
        trace: RetrievalTrace,
        allowed_source_refs: list[dict[str, object]],
        read_source_refs: list[dict[str, Any]],
        available_diagram_slots: set[str],
    ) -> PageValidationResult:
        markdown = _strip_llm_mermaid(str(payload.get("markdown") or ""))
        source_url_base = _source_url_base(repo.git_url, repo.commit_hash)
        source_refs, source_ref_errors = _validate_source_refs(
            repo_path=repo.path,
            requested_refs=payload.get("source_refs"),
            source_chunks=trace.source_chunks,
            allowed_source_refs=allowed_source_refs,
            source_url_base=source_url_base,
        )
        source_refs = _include_markdown_citation_refs(
            markdown,
            source_refs,
            allowed_source_refs,
            source_url_base=source_url_base,
        )
        source_refs = _filter_unused_source_refs(markdown, source_refs)
        if not source_refs:
            validation_errors = [*source_ref_errors, "At least one valid source_ref is required."]
        else:
            source_refs = _merge_recorded_source_refs(
                source_refs,
                read_source_refs,
                source_url_base=source_url_base,
            )
            validation_errors = []
            markdown = _strip_unknown_citation_markers(markdown, source_refs)

        validation_errors.extend(_validate_page_markdown(markdown, title))
        validation_errors.extend(_validate_citation_markers(markdown, source_refs))
        validation_errors.extend(_validate_diagram_placeholders(markdown, available_diagram_slots))
        return PageValidationResult(
            markdown=markdown,
            source_refs=source_refs,
            errors=validation_errors,
        )


def page_json_repair_payload(
    user_payload: dict[str, Any],
    previous_response: str,
    validation_errors: list[str],
) -> dict[str, Any]:
    return {
        **user_payload,
        "previous_response": previous_response[:6000],
        "validation_errors": validation_errors,
        "repair_instructions": (
            "Repair the page response. Return one valid JSON object only, with title, "
            "markdown, and source_refs. Use only diagram placeholders listed in diagram_slots. "
            "Do not include prose, comments, Markdown fences around the JSON, or trailing commas."
        ),
    }


def page_validation_repair_payload(
    user_payload: dict[str, Any],
    previous_response: dict[str, Any],
    validation_errors: list[str],
) -> dict[str, Any]:
    return {
        **user_payload,
        "previous_response": previous_response,
        "validation_errors": validation_errors,
        "repair_instructions": (
            "Repair the page so it validates. Keep the same title, include the required "
            "Purpose and Scope section, choose source_refs from allowed_source_refs, and "
            "only use [[S#]] markers for source_refs you return. Remove any unknown diagram "
            "placeholder, or use exact placeholders from diagram_slots."
        ),
    }


def _merge_recorded_source_refs(
    source_refs: list[dict[str, Any]],
    read_source_refs: list[dict[str, Any]],
    *,
    source_url_base: str | None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for ref in [*source_refs, *read_source_refs]:
        file_path = ref.get("file_path")
        start_line = ref.get("start_line")
        end_line = ref.get("end_line")
        if (
            not isinstance(file_path, str)
            or not isinstance(start_line, int)
            or not isinstance(end_line, int)
        ):
            continue
        key = (file_path, start_line, end_line)
        if key in seen:
            if ref.get("read_via"):
                for existing_ref in merged:
                    if (
                        existing_ref.get("file_path"),
                        existing_ref.get("start_line"),
                        existing_ref.get("end_line"),
                    ) == key:
                        existing_ref.setdefault("read_via", ref["read_via"])
                        break
            continue
        seen.add(key)
        merged_ref = dict(ref)
        if source_url_base and "source_url" not in merged_ref:
            merged_ref["source_url"] = _source_url(source_url_base, file_path, start_line, end_line)
        merged.append(merged_ref)
    return merged
