import asyncio
import json
from pathlib import Path

from backend.app.database import SQLiteStore
from backend.app.mcp_server import CodeWikiMCPServer
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.lite import init_lite_repo, prepare_lite_mcp_store


def test_mcp_initialize_and_lists_tools(tmp_path: Path) -> None:
    server = CodeWikiMCPServer(store=SQLiteStore(tmp_path / "codewiki.sqlite3"))

    initialize = asyncio.run(
        server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
    )
    assert initialize is not None
    assert initialize["result"]["serverInfo"]["name"] == "codewiki"
    assert initialize["result"]["capabilities"] == {"tools": {}}

    tools = asyncio.run(
        server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    )
    assert tools is not None
    tool_names = {tool["name"] for tool in tools["result"]["tools"]}
    assert "codewiki_repo_add" in tool_names
    assert "codewiki_repo_delete" in tool_names
    assert "codewiki_repo_scan" in tool_names
    assert "codewiki_files_tree" in tool_names
    assert "codewiki_update" in tool_names
    assert "codewiki_graph_status" in tool_names
    assert "codewiki_graph_callers" in tool_names
    assert "codewiki_context" in tool_names
    assert "codewiki_trace" in tool_names
    assert "codewiki_node" in tool_names
    assert "codewiki_wiki_catalog_generate" in tool_names
    assert "codewiki_wiki_translate" in tool_names
    assert "codewiki_graph_search" in tool_names
    assert "codewiki_ask" in tool_names


def test_mcp_ignores_notifications(tmp_path: Path) -> None:
    server = CodeWikiMCPServer(store=SQLiteStore(tmp_path / "codewiki.sqlite3"))

    response = asyncio.run(
        server.handle_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
    )

    assert response is None


def test_mcp_repo_add_analyze_and_graph_search(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def answer():\n    return 42\n", encoding="utf-8")

    server = CodeWikiMCPServer(store=SQLiteStore(tmp_path / "codewiki.sqlite3"))

    added = _call_tool(
        server,
        "codewiki_repo_add",
        {"path": str(repo_dir), "name": "demo"},
    )
    assert added["name"] == "demo"

    analysis = _call_tool(
        server,
        "codewiki_analyze",
        {"repo": added["id"], "community_summaries": False},
    )
    assert analysis["analysis"]["status"] == "done"

    hits = _call_tool(
        server,
        "codewiki_graph_search",
        {"repo": added["id"], "query": "answer", "type": "function"},
    )
    assert hits
    assert hits[0]["node"]["name"] == "answer"

    files = _call_tool(server, "codewiki_files_tree", {"repo": added["id"]})
    assert files["files"][0]["path"] == "main.py"

    status = _call_tool(server, "codewiki_graph_status", {"repo": added["id"]})
    assert status["node_count"] >= 2

    context = _call_tool(server, "codewiki_context", {"repo": added["id"], "task": "answer"})
    assert "answer" in context["text"]

    node = _call_tool(server, "codewiki_node", {"repo": added["id"], "symbol": "answer"})
    assert node["node"]["name"] == "answer"

    (repo_dir / "main.py").write_text("def answer():\n    return 43\n", encoding="utf-8")
    stale_context = _call_tool(server, "codewiki_context", {"repo": added["id"], "task": "answer"})
    assert stale_context["pending_sync"] is True
    assert stale_context["pending_files"] == ["main.py"]
    assert stale_context["text"].startswith("WARNING: index has pending file changes.")

    deleted = _call_tool(server, "codewiki_repo_delete", {"repo": added["id"]})
    assert deleted == {"repo_id": added["id"], "deleted": True}


def test_lite_mcp_store_catches_up_existing_index(tmp_path: Path) -> None:
    repo_dir = tmp_path / "lite-repo"
    repo_dir.mkdir()
    source = repo_dir / "main.py"
    source.write_text("def answer():\n    return 42\n", encoding="utf-8")
    store, repo, _db_path = init_lite_repo(path=repo_dir)
    analysis = asyncio.run(
        AnalysisService(store=store).analyze_with_community_summaries(
            repo.id,
            name_communities=False,
        )
    )
    assert analysis.analysis.status == "done"
    store.close()

    source.write_text("def answer():\n    return 43\n", encoding="utf-8")
    caught_up_store = prepare_lite_mcp_store(path=repo_dir)
    try:
        context = GraphQueryService(store=caught_up_store).node_context(repo.id, "answer")
    finally:
        caught_up_store.close()

    assert "return 43" in context.text


def _call_tool(server: CodeWikiMCPServer, name: str, arguments: dict[str, object]):
    response = asyncio.run(
        server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
    )
    assert response is not None
    assert response["result"]["isError"] is False
    return json.loads(response["result"]["content"][0]["text"])
