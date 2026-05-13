# Code Wiki Platform

Single-user Code Wiki platform for AST-based code graph analysis, GraphRAG retrieval, and LiteLLM-powered wiki generation.

## Current Scope

- FastAPI backend scaffold.
- LiteLLM-first gateway abstraction.
- AST, graph, GraphRAG, wiki, and ask service boundaries.
- React/Vite frontend scaffold with graph/wiki/ask pages.
- Design document copied to `docs/design.md`.

## Development

```bash
# backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn backend.app.main:app --reload

# CLI
codewiki analyze .
codewiki graphrag build
codewiki ask "How does the main workflow fit together?"

# Optional: give a repo a friendly name for later
codewiki repos add . --name my-repo
codewiki update my-repo

# frontend
cd frontend
npm install
npm run dev
```

## Notes

The first implementation milestone is to make repo scanning, AST extraction, and code graph persistence reliable before adding model-heavy workflows.
