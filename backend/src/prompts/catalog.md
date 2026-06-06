You are generating a DeepWiki-style Code Wiki catalog from a repository graph and
repository context.

Analysis workflow:

- First read the repository README, entry points, compact directory tree, and graph
  evidence in the payload before deciding pages.
- Treat the directory tree and graph as a module map. Group related files, symbols,
  routes, models, and workflows into logical developer-facing modules.
- Identify the main systems, capabilities, workflows, public surfaces, data contracts,
  and UI or API areas. Use individual files only as evidence for those boundaries.
- Cross-check each proposed page against source_hints, graph nodes, source chunks,
  entry points, or README claims.
- If a topic is only weakly evidenced, merge it into a broader page instead of
  creating a thin page.
- Prefer a leaf-first mindset: child pages carry implementation detail, while parent
  categories or parent pages summarize how those children fit together. When a parent
  would otherwise cover many unrelated responsibilities, split it into children.

Organization goals:

- Build a navigable documentation tree, not a flat list of summaries.
- Consider audience explicitly: new developers need "Getting Started" or a quick
  orientation, users need a "User Guide" or "How to Use" section, contributors need
  "Architecture" and "Developer Guide" sections, and operators need "Configuration",
  "Deployment", or "Operations" only when those concerns are evidenced.
- Prefer a DeepWiki-like progression when evidence supports it: Overview, Architecture,
  Reading Guide, Dependencies, Getting Started/User Guide, Core Workflows, API
  Reference, Developer Guide, and Operations.
- Include at least one "how to use" section and one "how it works" section when the
  repository has both API or UI surfaces and internal implementation layers.
- Start with top-level "Overview", "Architecture", "Reading Guide", and
  "Dependencies" pages, then group pages by real systems, layers, workflows, data
  models, APIs, services, and frontend surfaces that appear in the provided graph.
- Use the top-level section, total page, and depth ranges from `granularity_contract`.
  Use children aggressively when a subsystem has enough retrieved evidence to justify
  drill-down pages.
- A parent can contain category children when a layer has several distinct workflows
  or surfaces, but do not exceed the configured `catalog_scale.hard_limits.max_depth`.
- Follow the `catalog_scale` and `granularity_contract` values in the payload. Treat
  `catalog_scale.hard_limits.max_total_items` as the maximum total catalog items,
  counting both pages and categories.
- Use `kind: "category"` for parent section pages that should receive lightweight
  overview content and point readers to child pages. Use `kind: "page"` for focused
  documents that carry implementation detail.
- Prefer detailed content for leaf pages. Parent category pages should summarize the
  child section, explain the mental model, and avoid repeating child implementation
  details.
- Leaf pages should be narrow enough that `source_hints` are focused. A leaf should
  normally cover one workflow stage, route/API group, data model family, UI view,
  provider integration, export format, CLI/automation flow, or extension point.
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
- Split broad categories into concrete children. For example, "Backend Services" can
  have "API Routes", "Graph Analysis", "GraphRAG Retrieval", "Wiki Generation",
  "Persistence", and "Incremental Updates" when those boundaries are evidenced.
  "Frontend" can have "Graph Explorer", "Wiki Reader", "Ask Interface", "Exports",
  and "Settings" when evidenced.
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
- If a complex subsystem has several distinct responsibilities, create a category
  plus multiple focused leaf pages rather than one broad implementation page.
- Use `module_candidates` as a shortlist of directories and symbol clusters that
  deserve detailed splitting. Large candidates should normally become categories or
  multiple leaf pages unless the evidence shows they are trivial.

Rules:

- Use only the provided graph context, community summaries, nodes, edges, and source
  references.
- Do not invent modules, APIs, files, dependencies, or deployment surfaces.
- Return a concise hierarchy suitable for a developer-facing wiki.
- Return only JSON in the requested shape.
- Do not create pages for individual helpers, single tests, or isolated classes unless
  they are the primary public surface of the repository.
- Do not collapse API, storage, background jobs, rendering, exports, and configuration
  into one page when source evidence shows they are separate concerns.

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
