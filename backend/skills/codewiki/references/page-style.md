# CodeWiki Page Style

Write concise engineering documentation for someone navigating the codebase.

Use this shape by default:

```markdown
# Page Title

One short paragraph explaining what this page covers and why it matters. [[S1]]

## Key Files

- `path/to/file.ts`: what role it plays. [[S1]]

## How It Works

Explain the main flow in evidence-backed steps. Cite each concrete code claim.

## Notes

Mention constraints, extension points, or caveats only when the evidence supports them.
```

Rules:

- Every factual claim about code should be supported by `[[S#]]`.
- Use exact file paths from evidence.
- Prefer short sections over long prose.
- Keep uncertain or inferred statements explicitly framed as inference.
- Do not mention missing evidence unless it changes how the page should be used.
