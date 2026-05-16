You are generating one DeepWiki-style Code Wiki page.

You must execute this workflow in three ordered phases before writing. Treat these
phases as a hard contract, not as suggestions:
- GATHER: use `readfile_evidence.reads` as the mandatory ReadFile tool output. Inspect
  the topic, source_hints, source_chunks, graph_facts, and allowed_source_refs to
  identify the actual files and symbols involved. If the mandatory ReadFile evidence
  does not support a detail, do not present the detail as fact.
- THINK: map the subsystem responsibility, dependencies, data/control flow, and
  boundaries. Identify what uses this subsystem, what it uses, what data it moves,
  and where errors or edge cases are handled. Verify every planned claim against
  ReadFile evidence, source_chunks, or graph_facts.
- WRITE: only after GATHER and THINK, produce concise, source-grounded Markdown and
  return it as JSON.

Page structure:
- The markdown must start with "# {title}".
- Immediately after the title, write "## Purpose and Scope" with 1-3 concise
  paragraphs describing what this page covers and what it intentionally excludes.
- In "Purpose and Scope", include one direct sentence that states the subsystem's
  primary responsibility.
- Write like DeepWiki: concise, source-grounded, and oriented around how the subsystem
  fits into the larger repository. Prefer short paragraphs, compact tables, and
  explicit relationships between files, APIs, data structures, and workflows.
- Use tables as a primary presentation format for dense technical information:
  component responsibilities, routes, data shapes, configuration keys, workflows,
  failure modes, extension points, and source-backed comparisons.
- Add inline source citations with the exact `[[S#]]` markers from `allowed_source_refs`
  after concrete claims about files, functions, routes, data models, or control flow.
- Prefer citations whose ranges appear in `readfile_evidence.recorded_source_refs`.
  Those refs are automatically recorded as files read by the page-generation tool.
- Every concrete factual claim should have at least one nearby citation marker. Prefer
  the narrowest available source range from `allowed_source_refs`; avoid citing a broad
  chunk when a smaller cited chunk supports the claim.
- If a section makes several related claims, finish the section with a compact
  `Sources: [[S1]] [[S2]]` line, using only refs returned in `source_refs`.
- Then choose the most relevant sections from: "System Context", "Core Components",
  "Control Flow", "Data Model", "API Surface", "Configuration", "Frontend Flow",
  "Extension Points", "Failure Handling", "Testing", and "Operational Notes".
- Use compact tables when they make ownership, files, symbols, routes, or data shapes
  easier to scan.
- Name concrete files, functions, classes, endpoints, models, and relationships from
  the provided context. Avoid generic tutorial prose.
- When catalog_context contains related pages, mention only directly related pages by
  their provided titles or paths. Do not invent wiki links or pages.
- Do not include "Sources", "Relevant source files", "Related Pages", or Mermaid
  sections; the server and frontend inject those from validated source references,
  catalog context, and graph edges.
- The server chooses Mermaid diagrams from graph facts only. It may use component
  maps, left-to-right data flow, top-down control flow, sequence diagrams, and class
  diagrams. Write the prose so those diagrams are introduced naturally, but do not
  emit Mermaid code.
- Do not include an "On this page" section; the frontend derives it from headings.

Detail requirements:
- Cover the subsystem lifecycle or control flow when the evidence shows one.
- Describe upstream dependencies, downstream consumers, and important boundary points.
- Identify data structures, persisted records, DTOs, request/response shapes, or
  configuration keys when they are present in source_chunks or graph_facts.
- Explain important failure modes, validation behavior, retries, draft/error states,
  or fallback paths when the source evidence includes them.
- For API or frontend pages, include route/component/action tables when supported by
  the retrieved context.
- For service or pipeline pages, include a component/responsibility/evidence table.
- Use tests as evidence for behavior only when they are present in the retrieved
  context; do not let tests dominate a non-testing page.
- If expected information is not visible in the provided source evidence, say so
  briefly instead of guessing. Missing evidence is useful information: add a short
  "Missing evidence:" note when expected lifecycle, configuration, error handling, or
  recovery behavior is not exposed by the retrieved source.

Rules:
- Every factual claim about code must be supported by ReadFile evidence, source chunks,
  or graph edges.
- Do not ignore the mandatory ReadFile evidence. If readfile_evidence.reads is empty,
  say that direct source evidence is missing instead of guessing.
- Code examples must come from source chunks or be explicitly marked as pseudocode.
- Prefer no code examples over fabricated examples. If including code, use exact code
  from source_chunks and cite it through source_refs.
- Every code block copied from source must have a nearby citation marker. Do not invent
  examples, signatures, request payloads, or configuration defaults.
- source_refs must include the exact file ranges used for the page and must be chosen
  from allowed_source_refs. You may provide only `citation_id` when it exactly matches
  an allowed source ref.
- Do not use citation markers that are absent from the returned source_refs array.
- Return only JSON in the requested shape.
