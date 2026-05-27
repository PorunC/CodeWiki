from __future__ import annotations

import asyncio

import click

from backend.app.cli.common import echo_json, graph_status_payload, resolve_repo, run_click_errors
from backend.app.database import CodeWikiStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.incremental.watcher import IncrementalUpdateWatcher, WatchIterationResult
from backend.app.services.lite import create_lite_store, init_lite_repo, lite_database_path, uninit_lite_repo
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.repo_scanner.tree import file_payload, file_tree_payload


def register(main: click.Group) -> None:
    @main.group("lite")
    def lite_group() -> None:
        """Use a project-local, no-LLM CodeWiki index for agent workflows."""

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
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def files(path: str, source_only: bool, as_tree: bool, as_json: bool) -> None:
        """List or tree files for the lightweight repository."""
        store, repo = _lite_repo(path)
        scan = run_click_errors(lambda: RepoScanner().scan(repo.path, name=repo.name, source_type=repo.source_type))
        payload = {
            "repo_id": repo.id,
            "root": file_tree_payload(repo, scan.files),
            "files": [file_payload(scanned_file) for scanned_file in scan.files],
            "scanned_count": scan.scanned_count,
            "ignored_count": scan.ignored_count,
            "skipped_count": scan.skipped_count,
        }
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
