from pathlib import Path

from backend.app.services.repo_context import RepositoryContextBuilder


def test_repository_context_collects_readme_tree_and_entry_points(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n\nA small app.\n")
    (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    (repo / "backend").mkdir()
    (repo / "backend" / "app").mkdir()
    (repo / "backend" / "app" / "main.py").write_text("app = object()\n")
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text('{"dependencies":{"react":"latest"}}\n')
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "ignored.js").write_text("ignored\n")

    context = RepositoryContextBuilder(max_tree_depth=2).build(str(repo))

    assert context.project_type == "fullstack:python+frontend"
    assert "README.md" in context.key_files
    assert "backend/app/main.py" in context.entry_points
    assert "node_modules" not in context.directory_tree
    assert "A small app." in context.readme_content
