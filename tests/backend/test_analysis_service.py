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
    assert {node.type for node in nodes} >= {"repository", "file", "class", "function", "method"}
    assert any(node.name == "os" and node.type == "module" for node in nodes)
    assert any(edge.type == "contains" for edge in edges)
    assert any(edge.type == "imports" for edge in edges)
    assert any(edge.type == "calls" for edge in edges)


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
