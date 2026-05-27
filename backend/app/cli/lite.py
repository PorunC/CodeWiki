from __future__ import annotations

import asyncio
from typing import Any, cast

import click

from backend.app.cli.common import echo_json, graph_status_payload, resolve_repo, run_click_errors
from backend.app.database import CodeWikiStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.incremental.watcher import IncrementalUpdateWatcher, WatchIterationResult
from backend.app.services.lite import create_lite_store, init_lite_repo, lite_database_path, uninit_lite_repo
from backend.app.services.lite_agents import (
    AgentInstallResult,
    AgentTarget,
    InstallLocation,
    install_lite_agents,
    print_lite_agent_config,
    resolve_agent_targets,
    uninstall_lite_agents,
)
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.repo_scanner.tree import file_payload, file_tree_payload


def register(main: click.Group) -> None:
    @main.group("lite")
    def lite_group() -> None:
        """Use a project-local, no-LLM CodeWiki index for agent workflows."""

    @lite_group.group("agents")
    def agents_group() -> None:
        """Configure Codex and Claude Code to use Lite Mode over MCP."""

    @agents_group.command("install")
    @click.argument("path", required=False, default=".")
    @click.option(
        "--target",
        default="all",
        show_default=True,
        help="Agent target: claude, codex, all, auto, none, or comma-separated values.",
    )
    @click.option(
        "--location",
        type=click.Choice(["global", "local"]),
        default="local",
        show_default=True,
        help="Write user-wide or project-local agent config.",
    )
    @click.option(
        "--auto-allow/--no-auto-allow",
        default=True,
        show_default=True,
        help="Add Claude Code MCP permissions for CodeWiki Lite tools.",
    )
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def agents_install(
        path: str,
        target: str,
        location: str,
        auto_allow: bool,
        as_json: bool,
    ) -> None:
        """Install Lite Mode MCP config for agent CLIs."""
        install_location = cast(InstallLocation, location)
        targets = run_click_errors(lambda: resolve_agent_targets(target, location=install_location))
        results = run_click_errors(
            lambda: install_lite_agents(
                targets=targets,
                location=install_location,
                project_path=path,
                auto_allow=auto_allow,
            )
        )
        if as_json:
            echo_json(results)
            return
        _echo_agent_results(results)
        if location == "local" and "codex" in target.lower():
            click.echo("Codex CLI has no project-local config; use --location global for Codex.")

    @agents_group.command("uninstall")
    @click.argument("path", required=False, default=".")
    @click.option(
        "--target",
        default="all",
        show_default=True,
        help="Agent target: claude, codex, all, auto, none, or comma-separated values.",
    )
    @click.option(
        "--location",
        type=click.Choice(["global", "local"]),
        default="local",
        show_default=True,
        help="Remove user-wide or project-local agent config.",
    )
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def agents_uninstall(path: str, target: str, location: str, as_json: bool) -> None:
        """Remove Lite Mode MCP config from agent CLIs."""
        install_location = cast(InstallLocation, location)
        targets = run_click_errors(lambda: resolve_agent_targets(target, location=install_location))
        results = run_click_errors(
            lambda: uninstall_lite_agents(
                targets=targets,
                location=install_location,
                project_path=path,
            )
        )
        if as_json:
            echo_json(results)
            return
        _echo_agent_results(results)

    @agents_group.command("print-config")
    @click.argument("target", type=click.Choice(["claude", "codex"]))
    @click.argument("path", required=False, default=".")
    @click.option(
        "--location",
        type=click.Choice(["global", "local"]),
        default="local",
        show_default=True,
        help="Print user-wide or project-local config.",
    )
    def agents_print_config(target: str, path: str, location: str) -> None:
        """Print a Lite Mode MCP config snippet without writing files."""
        agent_target = cast(AgentTarget, target)
        install_location = cast(InstallLocation, location)
        click.echo(
            run_click_errors(
                lambda: print_lite_agent_config(
                    target=agent_target,
                    location=install_location,
                    project_path=path,
                )
            ),
            nl=False,
        )

    @lite_group.command("init")
    @click.argument("path", required=False, default=".")
    @click.option("--name", help="Repository display name.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def init(path: str, name: str | None, as_json: bool) -> None:
        """Initialize a lightweight .codewiki index for PATH."""
        store, repo, db_path = run_click_errors(lambda: init_lite_repo(path=path, name=name))
        payload = {"repo": repo, "database_path": db_path}
        store.close()
        if as_json:
            echo_json(payload)
            return
        click.echo(f"Initialized lite index for {repo.name}")
        click.echo(str(db_path))

    @lite_group.command("uninit")
    @click.argument("path", required=False, default=".")
    @click.option("--force", is_flag=True, help="Remove the lite index without prompting.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def uninit(path: str, force: bool, as_json: bool) -> None:
        """Remove the lightweight .codewiki index for PATH."""
        db_path = lite_database_path(path)
        if not force and not as_json:
            click.confirm(f"Remove lite index at {db_path.parent}?", abort=True)
        deleted = run_click_errors(lambda: uninit_lite_repo(path))
        payload = {"database_path": db_path, "deleted": deleted}
        if as_json:
            echo_json(payload)
            return
        click.echo(f"Removed {db_path.parent}" if deleted else f"No lite index found at {db_path.parent}")

    @lite_group.command("index")
    @click.argument("path", required=False, default=".")
    @click.option("--name", help="Repository display name.")
    @click.option("--force", is_flag=True, help="Force a full rebuild.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def index(path: str, name: str | None, force: bool, as_json: bool) -> None:
        """Build the lightweight graph index without LLM or Wiki generation."""
        store, repo, db_path = run_click_errors(lambda: init_lite_repo(path=path, name=name))
        analysis = run_click_errors(
            lambda: asyncio.run(
                AnalysisService(store=store).analyze_with_community_summaries(
                    repo.id,
                    name_communities=False,
                    force=force,
                )
            ),
            capture_stdout=as_json,
        )
        result = analysis.analysis
        payload = {
            "database_path": db_path,
            "run_id": result.run_id,
            "repo_id": result.repo_id,
            "status": result.status,
            "mode": result.mode,
            **result.stats(),
        }
        store.close()
        if as_json:
            echo_json(payload)
            return
        click.echo(
            f"Lite index {result.status}: {result.node_count} nodes, "
            f"{result.edge_count} edges, {result.community_count} communities"
        )
        click.echo(str(db_path))

    @lite_group.command("sync")
    @click.argument("path", required=False, default=".")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def sync(path: str, as_json: bool) -> None:
        """Incrementally refresh the lightweight graph index."""
        store = _lite_store(path)
        repo = run_click_errors(lambda: resolve_repo(store, path))
        result = run_click_errors(lambda: IncrementalUpdater(store=store).update(repo.id, refresh_chunks=False))
        payload = {"repo_id": repo.id, "run_id": result.run_id, "status": result.status, **result.stats()}
        store.close()
        if as_json:
            echo_json(payload)
            return
        click.echo(
            f"Lite sync {result.status}: {len(result.plan.affected_files)} affected files, "
            f"{result.node_count} nodes, {result.edge_count} edges"
        )

    @lite_group.command("watch")
    @click.argument("path", required=False, default=".")
    @click.option("--interval", default=2.0, show_default=True, type=float, help="Polling interval in seconds.")
    @click.option("--debounce", default=2.0, show_default=True, type=float, help="Quiet period before syncing.")
    def watch(path: str, interval: float, debounce: float) -> None:
        """Watch PATH and keep the lightweight graph index fresh."""
        store, repo = _lite_repo(path)
        click.echo(f"Watching lite index for {repo.name}. Press Ctrl-C to stop.")

        def on_iteration(result: WatchIterationResult) -> None:
            if not result.changed:
                return
            click.echo(
                f"Synced {len(result.affected_files)} files: "
                f"{result.node_count} nodes, {result.edge_count} edges (run {result.run_id})"
            )

        try:
            IncrementalUpdateWatcher(store=store).run(
                repo.id,
                interval_seconds=interval,
                debounce_seconds=debounce,
                refresh_chunks=False,
                on_iteration=on_iteration,
            )
        except KeyboardInterrupt:
            click.echo("Stopped watching.")
        finally:
            store.close()

    @lite_group.command("status")
    @click.argument("path", required=False, default=".")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def status(path: str, as_json: bool) -> None:
        """Show lightweight index statistics."""
        store, repo, payload = _lite_status(path)
        store.close()
        if as_json:
            echo_json(payload)
            return
        click.echo(
            f"{payload['node_count']} nodes, {payload['edge_count']} edges, "
            f"{payload['file_count']} files"
        )
        if payload["pending_sync"]:
            click.echo(f"Pending sync: {len(payload['pending_files'])} files")
        else:
            click.echo("Pending sync: none")
        click.echo(str(lite_database_path(path)))

    @lite_group.command("query")
    @click.argument("search", required=False, default="")
    @click.argument("path", required=False, default=".")
    @click.option("--type", "node_type", help="Filter by graph node type.")
    @click.option("--language", help="Filter by language.")
    @click.option("--limit", default=20, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def query(
        search: str,
        path: str,
        node_type: str | None,
        language: str | None,
        limit: int,
        as_json: bool,
    ) -> None:
        """Search symbols in the lightweight index."""
        store, repo = _lite_repo(path)
        hits = run_click_errors(
            lambda: GraphQueryService(store=store).search(
                repo.id,
                search,
                types=[node_type] if node_type else None,
                languages=[language] if language else None,
                limit=limit,
            )
        )
        store.close()
        if as_json:
            echo_json(hits)
            return
        for hit in hits:
            node = hit.node
            location = f"{node.file_path}:{node.start_line}" if node.file_path else node.id
            click.echo(f"{hit.score:.2f}  {node.name} ({node.type})  {location}")

    @lite_group.command("callers")
    @click.argument("symbol")
    @click.argument("path", required=False, default=".")
    @click.option("--limit", default=20, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def callers(symbol: str, path: str, limit: int, as_json: bool) -> None:
        """List graph nodes that call or reference SYMBOL."""
        _echo_lite_relationships(path, symbol, "callers", limit, as_json)

    @lite_group.command("callees")
    @click.argument("symbol")
    @click.argument("path", required=False, default=".")
    @click.option("--limit", default=20, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def callees(symbol: str, path: str, limit: int, as_json: bool) -> None:
        """List graph nodes called or referenced by SYMBOL."""
        _echo_lite_relationships(path, symbol, "callees", limit, as_json)

    @lite_group.command("impact")
    @click.argument("symbol")
    @click.argument("path", required=False, default=".")
    @click.option("--depth", default=2, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def impact(symbol: str, path: str, depth: int, as_json: bool) -> None:
        """Show symbols potentially affected by changing SYMBOL."""
        store, repo = _lite_repo(path)
        result = run_click_errors(lambda: GraphQueryService(store=store).impact(repo.id, symbol, depth=depth))
        store.close()
        if as_json:
            echo_json(result)
            return
        click.echo(f"Impact: {len(result.nodes)} nodes, {len(result.edges)} edges")
        for item in sorted(result.nodes, key=lambda node: (node.file_path, node.start_line or 0, node.name))[:80]:
            location = f"{item.file_path}:{item.start_line}" if item.file_path else item.id
            click.echo(f"- {item.name} ({item.type}) {location}")

    @lite_group.command("context")
    @click.argument("task")
    @click.argument("path", required=False, default=".")
    @click.option("--max-files", default=12, show_default=True, type=int)
    @click.option("--max-nodes", default=160, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def context(task: str, path: str, max_files: int, max_nodes: int, as_json: bool) -> None:
        """Build agent-friendly source context for TASK."""
        store, repo = _lite_repo(path)
        result = run_click_errors(
            lambda: GraphQueryService(store=store).explore(
                repo.id,
                task,
                max_files=max_files,
                max_nodes=max_nodes,
            )
        )
        store.close()
        if as_json:
            echo_json(result)
            return
        click.echo(result.text)

    @lite_group.command("trace")
    @click.argument("from_symbol")
    @click.argument("to_symbol")
    @click.argument("path", required=False, default=".")
    @click.option("--max-depth", default=8, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def trace(from_symbol: str, to_symbol: str, path: str, max_depth: int, as_json: bool) -> None:
        """Trace a static call/reference path between two symbols."""
        store, repo = _lite_repo(path)
        result = run_click_errors(
            lambda: GraphQueryService(store=store).trace(
                repo.id,
                from_symbol,
                to_symbol,
                max_depth=max_depth,
            )
        )
        store.close()
        if as_json:
            echo_json(result)
            return
        click.echo(result.text)

    @lite_group.command("node")
    @click.argument("symbol")
    @click.argument("path", required=False, default=".")
    @click.option("--no-code", is_flag=True, help="Omit source snippets.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def node(symbol: str, path: str, no_code: bool, as_json: bool) -> None:
        """Show one symbol plus callers, callees, and source."""
        store, repo = _lite_repo(path)
        result = run_click_errors(
            lambda: GraphQueryService(store=store).node_context(
                repo.id,
                symbol,
                include_code=not no_code,
            )
        )
        store.close()
        if as_json:
            echo_json(result)
            return
        click.echo(result.text)

    @lite_group.command("files")
    @click.argument("path", required=False, default=".")
    @click.option("--source-only", is_flag=True, help="Only show source files.")
    @click.option("--tree", "as_tree", is_flag=True, help="Print a tree instead of a flat list.")
    @click.option("--live", is_flag=True, help="Scan the file system instead of reading indexed files.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def files(path: str, source_only: bool, as_tree: bool, live: bool, as_json: bool) -> None:
        """List or tree indexed files for the lightweight repository."""
        store, repo = _lite_repo(path)
        payload = _live_files_payload(repo) if live else _indexed_files_payload(store, repo.id, repo.name)
        store.close()
        if source_only:
            payload["files"] = [item for item in payload["files"] if item["is_source"]]
        if as_json:
            echo_json(payload)
            return
        if as_tree:
            _print_tree(payload["root"])
            return
        for item in payload["files"]:
            click.echo(f"{item['path']}  {item['language'] or 'text'}  {item['size_bytes']} bytes")

    @lite_group.command("affected")
    @click.argument("files", nargs=-1)
    @click.option("--path", "repo_path", default=".", show_default=True, help="Repository path.")
    @click.option("--stdin", "use_stdin", is_flag=True, help="Read changed files from stdin.")
    @click.option("--depth", default=5, show_default=True, type=int)
    @click.option("--test-glob", help="Custom glob used to identify test files.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def affected(
        files: tuple[str, ...],
        repo_path: str,
        use_stdin: bool,
        depth: int,
        test_glob: str | None,
        as_json: bool,
    ) -> None:
        """Find files and tests affected by changed files."""
        changed_files = list(files)
        if use_stdin:
            changed_files.extend(
                line.strip() for line in click.get_text_stream("stdin").read().splitlines() if line.strip()
            )
        store, repo = _lite_repo(repo_path)
        result = run_click_errors(
            lambda: GraphQueryService(store=store).affected(
                repo.id,
                changed_files,
                depth=depth,
                test_glob=test_glob,
            )
        )
        store.close()
        if as_json:
            echo_json(result)
            return
        click.echo(f"Affected files: {len(result.affected_files)}")
        if result.affected_tests:
            click.echo("Affected tests:")
            for file_path in result.affected_tests:
                click.echo(f"- {file_path}")


def _lite_store(path: str) -> CodeWikiStore:
    return create_lite_store(path)


def _lite_repo(path: str):
    store = create_lite_store(path)
    repo = run_click_errors(lambda: resolve_repo(store, path))
    return store, repo


def _lite_status(path: str):
    store, repo = _lite_repo(path)
    nodes, edges = run_click_errors(lambda: store.get_graph(repo.id))
    payload = graph_status_payload(repo.id, nodes, edges)
    plan = run_click_errors(lambda: IncrementalUpdater(store=store).plan(repo.id))
    payload["pending_sync"] = bool(plan.affected_files)
    payload["pending_files"] = plan.affected_files
    payload["changed_files"] = plan.changed_files
    payload["new_files"] = plan.new_files
    payload["deleted_files"] = plan.deleted_files
    payload["detection_strategy"] = plan.detection_strategy
    payload["database_path"] = str(lite_database_path(path))
    return store, repo, payload


def _live_files_payload(repo) -> dict[str, Any]:
    scan = run_click_errors(lambda: RepoScanner().scan(repo.path, name=repo.name, source_type=repo.source_type))
    return {
        "repo_id": repo.id,
        "root": file_tree_payload(repo, scan.files),
        "files": [file_payload(scanned_file) for scanned_file in scan.files],
        "scanned_count": scan.scanned_count,
        "ignored_count": scan.ignored_count,
        "skipped_count": scan.skipped_count,
        "source": "live",
    }


def _indexed_files_payload(store: CodeWikiStore, repo_id: str, repo_name: str) -> dict[str, Any]:
    nodes, _edges = run_click_errors(lambda: store.get_graph(repo_id))
    file_nodes = sorted(
        [node for node in nodes if node.type in {"file", "config"}],
        key=lambda node: node.file_path,
    )
    files = [
        {
            "path": node.file_path,
            "absolute_path": node.metadata.get("absolute_path", ""),
            "language": node.language,
            "is_source": bool(node.metadata.get("is_source", node.type == "file")),
            "size_bytes": _int_metadata(node.metadata.get("size_bytes")),
            "sha256": node.hash,
            "modified_at": node.metadata.get("modified_at", ""),
            "type": node.type,
        }
        for node in file_nodes
    ]
    return {
        "repo_id": repo_id,
        "root": _indexed_file_tree(repo_name, files),
        "files": files,
        "scanned_count": len(files),
        "ignored_count": 0,
        "skipped_count": 0,
        "source": "index",
    }


def _indexed_file_tree(repo_name: str, files: list[dict[str, Any]]) -> dict[str, object]:
    root: dict[str, object] = {"name": repo_name, "type": "directory", "children": []}
    for item in files:
        path = str(item["path"])
        current = root
        parts = path.split("/")
        for part in parts[:-1]:
            children = current.setdefault("children", [])
            assert isinstance(children, list)
            child = next(
                (
                    entry for entry in children
                    if isinstance(entry, dict) and entry.get("name") == part and entry.get("type") == "directory"
                ),
                None,
            )
            if child is None:
                child = {"name": part, "type": "directory", "children": []}
                children.append(child)
            current = child
        children = current.setdefault("children", [])
        assert isinstance(children, list)
        children.append(
            {
                "name": parts[-1],
                "type": "file",
                "path": path,
                "language": item.get("language"),
                "is_source": item.get("is_source"),
            }
        )
    _sort_tree(root)
    return root


def _int_metadata(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _sort_tree(node: dict[str, object]) -> None:
    children = node.get("children")
    if not isinstance(children, list):
        return
    children.sort(
        key=lambda child: (
            0 if isinstance(child, dict) and child.get("type") == "directory" else 1,
            str(child.get("name") if isinstance(child, dict) else child),
        )
    )
    for child in children:
        if isinstance(child, dict):
            _sort_tree(child)


def _echo_lite_relationships(
    path: str,
    symbol: str,
    mode: str,
    limit: int,
    as_json: bool,
) -> None:
    store, repo = _lite_repo(path)
    service = GraphQueryService(store=store)
    relationships = run_click_errors(
        lambda: (
            service.callers(repo.id, symbol, limit=limit)
            if mode == "callers"
            else service.callees(repo.id, symbol, limit=limit)
        )
    )
    store.close()
    if as_json:
        echo_json(relationships)
        return
    for item in relationships:
        click.echo(
            f"{item.source.name} ({item.source.type}) -[{item.edge.type}]-> "
            f"{item.target.name} ({item.target.type})"
        )


def _echo_agent_results(results: list[AgentInstallResult]) -> None:
    if not results:
        click.echo("No agent targets selected.")
        return
    for result in results:
        for file in result.files:
            click.echo(f"{result.target}: {file.action} {file.path}")
        for note in result.notes:
            click.echo(f"{result.target}: {note}")


def _print_tree(node: object, prefix: str = "") -> None:
    if not isinstance(node, dict):
        return
    name = str(node.get("name", ""))
    click.echo(f"{prefix}{name}/" if node.get("type") == "directory" else f"{prefix}{name}")
    children = node.get("children")
    if not isinstance(children, list):
        return
    for child in children:
        _print_tree(child, prefix=f"{prefix}  ")
