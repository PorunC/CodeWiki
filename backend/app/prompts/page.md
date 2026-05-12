You are generating one DeepWiki-style Code Wiki page.

Page structure:
- The markdown must start with "# {title}".
- Immediately after the title, write "## Purpose and Scope" with 1-3 concise
  paragraphs describing what this page covers and what it intentionally excludes.
- Write like DeepWiki: concise, source-grounded, and oriented around how the subsystem
  fits into the larger repository.
- Add inline source citations with the exact `[[S#]]` markers from `allowed_source_refs`
  after concrete claims about files, functions, routes, data models, or control flow.
- If a section makes several related claims, finish the section with a compact
  `Sources: [[S1]] [[S2]]` line, using only refs returned in `source_refs`.
- Then choose the most relevant sections from: "System Context", "Core Components",
  "Control Flow", "Data Model", "API Surface", "Configuration", "Frontend Flow",
  "Extension Points", and "Operational Notes".
- Use compact tables when they make ownership, files, symbols, routes, or data shapes
  easier to scan.
- Name concrete files, functions, classes, endpoints, models, and relationships from
  the provided context. Avoid generic tutorial prose.
- Do not include "Sources", "Relevant source files", or Mermaid sections; the server
  injects those from validated source references and graph edges.

Rules:
- Every factual claim about code must be supported by source chunks or graph edges.
- Code examples must come from source chunks or be explicitly marked as pseudocode.
- Prefer no code examples over fabricated examples. If including code, use exact code
  from source_chunks and cite it through source_refs.
- source_refs must include the exact file ranges used for the page and must be chosen
  from allowed_source_refs. You may provide only `citation_id` when it exactly matches
  an allowed source ref.
- Do not use citation markers that are absent from the returned source_refs array.
- Return only JSON in the requested shape.
