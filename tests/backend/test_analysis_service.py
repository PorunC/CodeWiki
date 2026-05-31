from pathlib import Path

import pytest

from backend.app.config import LLMProfileSettings, LLMSettings, Settings
from backend.app.database import SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.community.detector import DetectedCommunity
from backend.app.services.community.records import CommunityRecordBuilder
from backend.app.services.community.naming import CommunityNamingResult
from backend.app.services.graph import CodeGraphNode
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
    assert sum(result.community_count_by_level.values()) == result.community_count
    assert result.community_count >= 1
    assert {node.type for node in nodes} >= {"repository", "file", "class", "function", "method"}
    assert not any(node.name == "os" and node.type == "module" for node in nodes)
    assert all("provenance" in node.metadata for node in nodes)
    assert any(edge.type == "contains" for edge in edges)
    assert not any(edge.type == "imports" and edge.metadata.get("resolved") is False for edge in edges)
    assert any(edge.type == "calls" for edge in edges)
    assert all("provenance" in edge.metadata for edge in edges)
    assert all("confidence_level" in edge.metadata for edge in edges)
    assert all("reason" in edge.metadata for edge in edges)


def test_deterministic_community_names_use_file_evidence_for_init_and_dotfiles() -> None:
    init_node = CodeGraphNode(
        id="repo:file:backend/app/api/__init__.py",
        repo_id="repo",
        type="file",
        name="__init__.py",
        file_path="backend/app/api/__init__.py",
    )
    dotfile_node = CodeGraphNode(
        id="repo:file:.gitignore",
        repo_id="repo",
        type="file",
        name=".gitignore",
        file_path=".gitignore",
    )

    builder = CommunityRecordBuilder()

    assert builder.name(22, [init_node.id], {init_node.id: init_node}) == "Api Package"
    assert builder.name(19, [dotfile_node.id], {dotfile_node.id: dotfile_node}) == "Gitignore"


def test_community_record_builder_resolves_nested_parent_ids() -> None:
    node = CodeGraphNode(
        id="repo:file:api.py",
        repo_id="repo",
        type="file",
        name="api.py",
        file_path="api.py",
    )
    detected = [
        DetectedCommunity(key="parent", node_ids=[node.id], level=0, parent_key=None, rank=0),
        DetectedCommunity(key="child", node_ids=[node.id], level=1, parent_key="parent", rank=0),
        DetectedCommunity(key="detail", node_ids=[node.id], level=2, parent_key="child", rank=0),
    ]

    records = CommunityRecordBuilder().build_all("repo", detected, [node], [], "test")
    by_level = {record.level: record for record in records}

    assert by_level[1].parent_id == by_level[0].id
    assert by_level[2].parent_id == by_level[1].id


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
    assert runs[0].stats["community_count_by_level"] == result.community_count_by_level


def test_analyze_reuses_existing_graph_when_repo_is_unchanged(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def main():\n    return 1\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    service = AnalysisService(store=store)

    first = service.analyze(repo.id)
    second = service.analyze(repo.id)

    assert first.mode == "full"
    assert second.mode == "unchanged"
    assert second.parsed_file_count == 0
    assert second.reused_file_count == 1
    assert second.node_count == first.node_count
    assert store.list_analysis_runs(repo.id)[0].stats["mode"] == "unchanged"


@pytest.mark.asyncio
async def test_analyze_with_community_summaries_invokes_llm_namer(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def main():\n    return 1\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    namer = _FakeCommunityNamer()

    result = await AnalysisService(store=store).analyze_with_community_summaries(
        repo.id,
        community_namer=namer,
    )

    assert result.analysis.status == "done"
    assert result.community_naming is not None
    assert result.community_naming.status == "renamed"
    assert namer.repo_ids == [repo.id]


@pytest.mark.asyncio
async def test_analyze_with_community_summaries_skips_llm_when_unconfigured(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def main():\n    return 1\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))

    result = await AnalysisService(store=store).analyze_with_community_summaries(
        repo.id,
        settings=Settings(
            _env_file=None,
            llm=LLMSettings(
                default=LLMProfileSettings(model="provider/strong-coding-model"),
                profiles={
                    "community_summary": LLMProfileSettings(
                        model="provider/strong-coding-model",
                    )
                },
            ),
        ),
    )

    assert result.analysis.status == "done"
    assert result.community_naming is not None
    assert result.community_naming.status == "skipped"


def test_analyze_resolves_local_typescript_imports_and_fact_edges(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "models.ts").write_text(
        "\n".join(
            [
                "export interface User { id: string }",
                "export interface Loadable { load(): Promise<string> }",
                "export class BaseLoader {}",
            ]
        )
        + "\n"
    )
    (repo_dir / "routes.ts").write_text(
        "\n".join(
            [
                "import { BaseLoader, User } from './models';",
                "import { Loadable } from './models';",
                "export class Loader extends BaseLoader implements Loadable {}",
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
    assert {"defines", "exports", "imports", "inherits", "implements", "routes_to"} <= edge_types

    implements_edges = [edge for edge in edges if edge.type == "implements" and edge.metadata.get("interface") == "Loadable"]
    assert implements_edges
    assert implements_edges[0].is_inferred is False

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


def test_analyze_skips_unresolved_external_type_reference_nodes(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "worker.ts").write_text("export class Worker extends ExternalBase {}\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))

    AnalysisService(store=store).analyze(repo.id)
    nodes, edges = store.get_graph(repo.id)

    worker_node = next(node for node in nodes if node.type == "class" and node.name == "Worker")
    assert not any(node.type == "module" and node.name == "ExternalBase" for node in nodes)
    assert not any(
        edge.type == "inherits"
        and edge.source_id == worker_node.id
        and edge.metadata.get("base") == "ExternalBase"
        for edge in edges
    )


def test_analyze_records_confidence_tiers_and_edge_reasons(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text("def run():\n    return 1\n")
    (repo_dir / "api.py").write_text(
        "\n".join(
            [
                "from service import run",
                "",
                "def local_helper():",
                "    return 2",
                "",
                "def handler():",
                "    local_helper()",
                "    return run()",
            ]
        )
        + "\n"
    )
    (repo_dir / "loose.py").write_text("def loose():\n    return run()\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))

    AnalysisService(store=store).analyze(repo.id)
    nodes, edges = store.get_graph(repo.id)
    node_by_name = {node.name: node for node in nodes}

    import_edge = next(
        edge
        for edge in edges
        if edge.type == "imports" and edge.source_id.endswith(":file:api.py")
    )
    assert import_edge.confidence == 0.90
    assert import_edge.metadata["reason"] == "import-resolved"
    assert import_edge.metadata["resolution_tier"] == "import_scoped"

    imported_call = next(
        edge
        for edge in edges
        if edge.type == "calls"
        and edge.source_id == node_by_name["handler"].id
        and edge.target_id == node_by_name["run"].id
    )
    assert imported_call.confidence == 0.90
    assert imported_call.metadata["reason"] == "import-resolved"
    assert imported_call.metadata["resolution_tier"] == "import_scoped"

    same_file_call = next(
        edge
        for edge in edges
        if edge.type == "calls"
        and edge.source_id == node_by_name["handler"].id
        and edge.target_id == node_by_name["local_helper"].id
    )
    assert same_file_call.confidence == 0.95
    assert same_file_call.metadata["reason"] == "local-call"
    assert same_file_call.metadata["resolution_tier"] == "same_file"

    global_call = next(
        edge
        for edge in edges
        if edge.type == "calls"
        and edge.source_id == node_by_name["loose"].id
        and edge.target_id == node_by_name["run"].id
    )
    assert global_call.confidence == 0.50
    assert global_call.metadata["reason"] == "global"
    assert global_call.metadata["resolution_tier"] == "global"


def test_analyze_infers_references_and_config_usage(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "config.json").write_text('{"feature": true}\n')
    (repo_dir / "models.ts").write_text("export interface Settings { feature: boolean }\n")
    (repo_dir / "app.ts").write_text(
        "\n".join(
            [
                "import settings from './config.json';",
                "import { Settings } from './models';",
                "",
                "export function loadSettings(): Settings {",
                "  return settings as Settings;",
                "}",
            ]
        )
        + "\n"
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))

    AnalysisService(store=store).analyze(repo.id)
    nodes, edges = store.get_graph(repo.id)

    config_node = next(node for node in nodes if node.type == "config" and node.file_path == "config.json")
    schema_node = next(node for node in nodes if node.type == "schema" and node.name == "Settings")
    function_node = next(node for node in nodes if node.type == "function" and node.name == "loadSettings")

    assert config_node.metadata["config"] is True
    assert any(
        edge.type == "uses_config"
        and edge.target_id == config_node.id
        and edge.is_inferred
        for edge in edges
    )
    assert any(
        edge.type == "references"
        and edge.source_id == function_node.id
        and edge.target_id == schema_node.id
        and edge.is_inferred
        for edge in edges
    )


class _FakeCommunityNamer:
    def __init__(self) -> None:
        self.repo_ids: list[str] = []

    async def name_communities(self, repo_id: str) -> CommunityNamingResult:
        self.repo_ids.append(repo_id)
        return CommunityNamingResult(
            repo_id=repo_id,
            status="renamed",
            renamed_count=1,
            community_count=1,
            llm_run_ids=["run-1"],
            errors=[],
        )
