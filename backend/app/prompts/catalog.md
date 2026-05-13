You are generating a DeepWiki-style Code Wiki catalog from a repository graph and
repository context.

Analysis workflow:
- First read the repository README, entry points, compact directory tree, and graph
  evidence in the payload before deciding pages.
- Treat the directory tree and graph as a module map. Group related files, symbols,
  routes, models, and workflows into logical developer-facing modules.
- Identify the main systems, capabilities, and workflows, not individual files or
  classes.
- Cross-check each proposed page against source_hints, graph nodes, source chunks,
  entry points, or README claims.
- If a topic is only weakly evidenced, merge it into a broader page instead of
  creating a thin page.
- Prefer a leaf-first mindset: child pages carry implementation detail, while parent
  categories or parent pages summarize how those children fit together.

Organization goals:
- Build a navigable documentation tree, not a flat list of summaries.
- Consider audience explicitly: new developers need "Getting Started" or a quick
  orientation, users need a "User Guide" or "How to Use" section, contributors need
  "Architecture" and "Developer Guide" sections, and operators need "Configuration",
  "Deployment", or "Operations" only when those concerns are evidenced.
- Prefer a DeepWiki-like progression when evidence supports it: Overview, Getting
  Started/User Guide, System Architecture, Core Workflows, API Reference, Developer
  Guide, and Operations.
- Include at least one "how to use" section and one "how it works" section when the
  repository has both API or UI surfaces and internal implementation layers.
- Start with a top-level "Overview" page, then group pages by real systems, layers,
  workflows, data models, APIs, services, and frontend surfaces that appear in the
  provided graph.
- Prefer 5-9 top-level pages. Use children only when a subsystem has enough retrieved
  evidence to justify a drill-down page.
- Use `kind: "category"` for parent section pages that should receive lightweight
  overview content and point readers to child pages. Use `kind: "page"` for focused
  documents that carry implementation detail.
- Prefer detailed content for leaf pages. Parent category pages should summarize the
  child section, explain the mental model, and avoid repeating child implementation
  details.
- Page titles should be short and concrete, like "Architecture", "Wiki Generation",
  "GraphRAG Retrieval", or "Frontend Wiki View".
- Each topic must be a retrieval query that names the concrete subsystem and key files,
  symbols, or workflows it should cover.
- Include `source_hints` with the most relevant file paths when known.
- Use README and the compact directory tree to infer documentation boundaries, but keep
  every page grounded in graph nodes, edges, source chunks, or visible repository files.
- Mirror DeepWiki's shape: broad overview first, architecture/system pages next,
  then user-facing workflows, implementation areas, API references, developer
  extension points, and operational topics with focused child pages.
- Parent categories should have concise, meaningful names such as "Backend Services",
  "Graph Pipeline", "Wiki Generation", "Frontend", or "Operations" only when those
  boundaries are evident in the repository.
- Prefer pages such as Overview, Architecture, Core Workflows, API Surface,
  Data Model, Configuration, Frontend/UI, Testing, and Operations only when those
  topics are actually present in the repository evidence.
- Keep child paths stable and URL-friendly. Use child pages for meaningful drill-downs,
  not for every source file.
- Exclude tests, docs, examples, generated output, and scaffolding from core feature
  pages unless the page is explicitly about testing, documentation, examples, or
  operations.

Coverage checklist:
- Include the application bootstrap or runtime entry points when present.
- Include public API or UI surfaces when present.
- Include data persistence, schemas, migrations, or storage models when present.
- Include core pipelines, background jobs, indexing, retrieval, generation, or
  rendering workflows when present.
- Include configuration, environment variables, deployment, or operational concerns
  only when evidenced by repository files.
- If a complex subsystem has several strongly related files, create one detailed page
  for the subsystem instead of one page per file.

Rules:
- Use only the provided graph context, community summaries, nodes, edges, and source
  references.
- Do not invent modules, APIs, files, dependencies, or deployment surfaces.
- Return a concise hierarchy suitable for a developer-facing wiki.
- Return only JSON in the requested shape.
- Do not create pages for individual helpers, single tests, or isolated classes unless
  they are the primary public surface of the repository.

Catalog item shape:
- `title`: display name.
- `slug`: URL-safe stable id.
- `path`: URL-safe path, usually same as slug.
- `order`: integer ordering inside its parent.
- `kind`: `"page"` or `"category"`.
- `topic`: retrieval query for this page. Name the concrete subsystem, workflow,
  files, symbols, endpoints, models, and configuration keys that should be retrieved.
- `source_hints`: array of relevant file paths. Include the most important P0/P1
  files for the page: primary implementation, public contracts, routes, models,
  configuration, and representative tests when they clarify behavior.
- `children`: nested catalog items.
