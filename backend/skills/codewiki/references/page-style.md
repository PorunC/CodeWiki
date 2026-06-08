# CodeWiki Page Style

Write DeepWiki-style engineering documentation for someone navigating the codebase.
The page should explain how the evidenced subsystem works internally, not just list
files.

## Mandatory Shape

Use this shape unless the evidence is genuinely tiny:

```markdown
# Page Title

## Purpose and Scope

State the page boundary and the subsystem's primary responsibility. Mention what is
excluded when the catalog topic is narrow. Cite concrete code claims. [[S1]]

## Key Files

| File              | Role                                              | Evidence |
| ----------------- | ------------------------------------------------- | -------- |
| `path/to/file.ts` | Concrete responsibility in this page's subsystem. | [[S1]]   |

## Core Components

Explain concrete files, functions, classes, routes, models, hooks, or commands. Use
tables when more than two components are evidenced.

## Control Flow

Describe the main execution path with owners, inputs, outputs, side effects, and
failure or validation behavior when evidence supports it.

## Boundaries and Extension Points

Explain upstream dependencies, downstream consumers, configuration, persistence,
UI/API boundaries, or extension points only when the evidence supports them.
```

## Evidence Rules

- Every factual claim about code should have a nearby `[[S#]]` citation.
- Use citation IDs only from `allowed_source_refs`.
- Use exact file paths from evidence.
- Prefer concrete implementation details over generic tutorial prose.
- Do not invent APIs, files, functions, routes, wiki pages, config keys, or behavior.
- If expected lifecycle, error handling, configuration, or integration evidence is
  missing, state that briefly instead of guessing.

## Section Guidance

- For parent/category pages, synthesize how child pages relate and where shared
  control flow, data contracts, or dependencies cross child boundaries. Do not simply
  list child pages.
- For service or pipeline pages, include a component/responsibility table and a
  workflow table when evidence supports them.
- For API pages, include route/handler/request/response or command surface tables
  when evidence supports them.
- For frontend pages, include view/component/state/action/API-call relationships
  when evidence supports them.
- For persistence-heavy pages, include record/repository/state-transition tables
  when evidence supports them.

## Do Not Include

- Do not add `## Sources`, `## Relevant source files`, `## Related Pages`, or Mermaid
  sections. CodeWiki stores source refs and graph context separately.
- Do not add uncited summaries of broad architecture.
- Do not include code examples unless the code comes directly from evidence; mark any
  unavoidable sketch as pseudocode.
