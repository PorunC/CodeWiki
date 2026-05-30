import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.database import DocPageRecord, CodeWikiStore
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm.gateway import LLMGateway
from backend.app.services.llm.operations import CachedLLMService, LLMOperation
from backend.app.services.llm.run_recorder import LLMCallError
from backend.app.services.wiki.agent_tools import readfile_evidence_for_page
from backend.app.services.wiki.catalog import (
    _source_hints_from_item,
    _trace_with_source_hint_chunks,
)
from backend.app.services.wiki.diagrams import (
    _diagram_slots_payload,
    _graph_refs_from_trace,
    _mermaid_diagrams_from_trace,
    MermaidDiagram,
)
from backend.app.services.wiki.mermaid_validation import (
    validate_mermaid,
    validate_mermaid_blocks_async,
)
from backend.app.services.wiki.page_payload import PageGenerationPayloadBuilder
from backend.app.services.wiki.page_validation import (
    PageResponseValidator,
    page_json_repair_payload,
    page_validation_repair_payload,
)
from backend.app.services.wiki.prompts import _json_object, _load_prompt, _page_messages
from backend.app.services.wiki.sources import (
    _compose_page_markdown,
    _draft_markdown,
    _replace_citation_markers,
    _source_refs_from_chunks,
)
from backend.app.services.wiki.utils import slugify

PAGE_GENERATION_ATTEMPTS = 2
PAGE_RETRIEVAL_MAX_HOPS = 3
PAGE_CACHE_VERSION = "page:v5"
PAGE_PROMPT_VERSION = "page:deepwiki:v5"


@dataclass(frozen=True)
class PageGenerationResult:
    page: DocPageRecord
    validation_errors: list[str]


class WikiPageGenerator:
    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: CodeWikiStore,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store
        self.llm_service = CachedLLMService(store=self.store, llm=self.llm)
        self.payload_builder = PageGenerationPayloadBuilder(store=self.store)
        self.response_validator = PageResponseValidator()

    async def generate_page(
        self,
        repo_id: str,
        item: dict[str, Any],
        *,
        language_code: str = "en",
        parent_slug: str | None = None,
        child_pages: list[DocPageRecord] | None = None,
    ) -> PageGenerationResult:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        title = str(item.get("title") or "Untitled")
        slug = slugify(str(item.get("slug") or item.get("path") or title))
        topic = str(item.get("topic") or title)
        source_hints = _source_hints_from_item(item)
        trace = await self.retriever.retrieve(repo_id, topic, max_hops=PAGE_RETRIEVAL_MAX_HOPS)
        trace = _trace_with_source_hint_chunks(trace, self.store, repo_id, source_hints)
        graph_refs = _graph_refs_from_trace(trace)
        allowed_source_refs = _source_refs_from_chunks(trace.source_chunks)
        diagram_plan = _mermaid_diagrams_from_trace(trace, title=title, source_refs=[])
        readfile_evidence = readfile_evidence_for_page(
            repo_path=repo.path,
            allowed_source_refs=allowed_source_refs,
            source_hints=source_hints,
        )
        user_payload = self.payload_builder.build(
            repo,
            item,
            trace,
            title=title,
            slug=slug,
            topic=topic,
            parent_slug=parent_slug,
            language_code=language_code,
            source_hints=source_hints,
            allowed_source_refs=allowed_source_refs,
            readfile_evidence=readfile_evidence,
            child_pages=child_pages or [],
            diagram_slots=_diagram_slots_payload(diagram_plan),
        )
        prompt_contract = self.payload_builder.prompt_contract()

        payload: dict[str, Any] = {}
        markdown = ""
        source_refs: list[dict[str, Any]] = []
        validation_errors: list[str] = []
        attempt_payload = user_payload
        prompt = _load_prompt("page.md")

        for attempt in range(PAGE_GENERATION_ATTEMPTS):
            try:
                completion = await self.llm_service.complete(
                    repo_id,
                    LLMOperation(
                        task_type="page",
                        messages=_page_messages(
                            prompt,
                            prompt_contract,
                            attempt_payload,
                            validation_errors if attempt else [],
                        ),
                        input_payload=attempt_payload,
                        cache_namespace=PAGE_CACHE_VERSION,
                        cache_parts=(slug, trace.trace_id, "attempt", attempt + 1),
                        model_alias="page",
                        prompt_version=PAGE_PROMPT_VERSION,
                        response_format="json_object",
                    ),
                )
            except LLMCallError as exc:
                validation_errors = [f"LLM provider call failed: {exc}"]
                break
            result = completion.result

            try:
                payload = _json_object(result.content)
            except ValueError as exc:
                validation_errors = [str(exc)]
                self.store.update_llm_run_status(
                    completion.run.id,
                    status="error",
                    error=str(exc),
                )
                attempt_payload = page_json_repair_payload(
                    user_payload,
                    result.content,
                    validation_errors,
                )
                continue

            validation = self.response_validator.validate(
                repo=repo,
                payload=payload,
                title=title,
                trace=trace,
                allowed_source_refs=allowed_source_refs,
                read_source_refs=readfile_evidence.source_refs,
                available_diagram_slots={diagram.slot for diagram in diagram_plan},
            )
            markdown = validation.markdown
            source_refs = validation.source_refs
            validation_errors = validation.errors
            if not validation_errors:
                break

            self.store.update_llm_run_status(
                completion.run.id,
                status="error",
                error="; ".join(validation_errors),
            )
            attempt_payload = page_validation_repair_payload(
                user_payload,
                payload,
                validation_errors,
            )

        status = "generated" if not validation_errors else "draft"
        if status == "generated":
            content_markdown = _replace_citation_markers(markdown, source_refs)
            diagrams = _mermaid_diagrams_from_trace(trace, title=title, source_refs=source_refs)
            markdown = _compose_page_markdown(content_markdown, diagrams, source_refs)
            mermaid_errors = await validate_mermaid_blocks_async(markdown)
            if mermaid_errors and diagrams:
                valid_diagrams = await _valid_mermaid_diagrams_async(diagrams)
                markdown = _compose_page_markdown(content_markdown, valid_diagrams, source_refs)
                mermaid_errors = await validate_mermaid_blocks_async(markdown)
            if mermaid_errors and diagrams:
                markdown = _compose_page_markdown(content_markdown, [], source_refs)
                mermaid_errors = await validate_mermaid_blocks_async(markdown)
            if mermaid_errors:
                validation_errors.extend(mermaid_errors)
                status = "draft"
                markdown = _draft_markdown(title, validation_errors)
        else:
            markdown = _draft_markdown(title, validation_errors)

        page = DocPageRecord(
            id=uuid.uuid4().hex,
            repo_id=repo_id,
            language_code=language_code,
            slug=slug,
            title=str(payload.get("title") or title),
            parent_slug=parent_slug,
            markdown=markdown,
            source_refs=source_refs,
            graph_refs=sorted(graph_refs),
            status=status,
            updated_at=None,
        )
        return PageGenerationResult(
            page=self.store.upsert_doc_page(page),
            validation_errors=validation_errors,
        )


async def _valid_mermaid_diagrams_async(
    diagrams: list[MermaidDiagram],
) -> list[MermaidDiagram]:
    valid_diagrams: list[MermaidDiagram] = []
    for diagram in diagrams:
        error = await _validate_mermaid_diagram_async(diagram)
        if error is None:
            valid_diagrams.append(diagram)
    return valid_diagrams


async def _validate_mermaid_diagram_async(diagram: MermaidDiagram) -> str | None:
    return await _validate_mermaid_lines_async(diagram.lines)


async def _validate_mermaid_lines_async(lines: list[str]) -> str | None:
    return await asyncio.to_thread(validate_mermaid, "\n".join(lines))
