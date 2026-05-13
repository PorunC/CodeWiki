from pathlib import Path

from backend.app.database import SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.repo_scanner import RepoScanner


def test_analyze_persists_first_code_graph(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text(
        "\n".join(
            [
                "import os",
                "",
                "class Service:",
                "    def run(self):",
                "        return os.getcwd()",
                "",
                "def build():",
                "    service = Service()",
                "    return service.run()",
            ]
        )
        + "\n"
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))

    result = AnalysisService(store=store).analyze(repo.id)
    nodes, edges = store.get_graph(repo.id)

    assert result.status == "done"
    assert result.scanned_count == 1
    assert result.parsed_file_count == 1
    assert result.node_count == len(nodes)
    assert result.edge_count == len(edges)
    assert result.community_count == len(store.list_graph_communities(repo.id))
    assert result.community_count >= 1
    assert {node.type for node in nodes} >= {"repository", "file", "class", "function", "method"}
    assert any(node.name == "os" and node.type == "module" for node in nodes)
    assert all("provenance" in node.metadata for node in nodes)
    assert any(edge.type == "contains" for edge in edges)
    assert any(edge.type == "imports" for edge in edges)
    assert any(edge.type == "calls" for edge in edges)
    assert all("provenance" in edge.metadata for edge in edges)
    assert all("confidence_level" in edge.metadata for edge in edges)


def test_store_lists_analysis_runs(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def main():\n    return 1\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))

    result = AnalysisService(store=store).analyze(repo.id)
    runs = store.list_analysis_runs(repo.id)

    assert [run.id for run in runs] == [result.run_id]
    assert runs[0].status == "done"
    assert runs[0].stats["node_count"] == result.node_count
    assert runs[0].stats["community_count"] == result.community_count


def test_analyze_resolves_local_typescript_imports_and_fact_edges(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "models.ts").write_text(
        "\n".join(
            [
                "export interface User { id: string }",
                "export class BaseLoader {}",
            ]
        )
        + "\n"
    )
    (repo_dir / "routes.ts").write_text(
        "\n".join(
            [
                "import { BaseLoader, User } from './models';",
                "export class Loader extends BaseLoader {}",
                "router.get('/users/:id', getUser);",
                "export function getUser(): User {",
                "  return { id: '1' };",
                "}",
            ]
        )
        + "\n"
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))

    result = AnalysisService(store=store).analyze(repo.id)
    nodes, edges = store.get_graph(repo.id)

    assert result.status == "done"
    assert any(node.type == "schema" and node.name == "User" for node in nodes)
    assert any(node.type == "endpoint" and node.name == "GET /users/:id" for node in nodes)

    edge_types = {edge.type for edge in edges}
    assert {"defines", "exports", "imports", "inherits", "routes_to"} <= edge_types

    local_import_edges = [
        edge
        for edge in edges
        if edge.type == "imports" and edge.metadata.get("import") == "./models"
    ]
    assert local_import_edges
    assert local_import_edges[0].metadata["resolved"] is True
    assert ":file:models.ts" in local_import_edges[0].target_id


def test_analyze_resolves_local_python_imports(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "__init__.py").write_text("")
    (repo_dir / "service.py").write_text("def run():\n    return 1\n")
    (repo_dir / "api.py").write_text("from service import run\n\ndef handler():\n    return run()\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))

    AnalysisService(store=store).analyze(repo.id)
    _nodes, edges = store.get_graph(repo.id)

    local_import_edges = [
        edge for edge in edges if edge.type == "imports" and edge.metadata.get("resolved") is True
    ]
    assert any(edge.source_id.endswith(":file:api.py") and edge.target_id.endswith(":file:service.py") for edge in local_import_edges)
