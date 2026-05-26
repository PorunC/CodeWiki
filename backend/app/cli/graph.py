import click
from typing import cast

from backend.app.cli.common import (
    echo_json,
    echo_table,
    graph_status_payload,
    resolve_repo,
    run_click_errors,
    store_from_context,
)
from backend.app.services.graph.query import GraphQueryService


def register(main: click.Group) -> None:
    @main.group("graph")
    def graph_group() -> None:
        """Query the analyzed code graph."""

    @graph_group.command("search")
    @click.argument("query", required=False, default="")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--type", "node_type", help="Filter by graph node type.")
    @click.option("--language", help="Filter by language.")
    @click.option("--path", "path_filter", help="Filter by file path substring.")
    @click.option("--name", "name_filter", help="Filter by node name substring.")
    @click.option("--limit", default=20, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def graph_search(
        ctx: click.Context,
        query: str,
        repo: str | None,
        repo_option: str | None,
        node_type: str | None,
        language: str | None,
        path_filter: str | None,
        name_filter: str | None,
        limit: int,
        as_json: bool,
    ) -> None:
        """Search graph symbols by name, path, signature, or docstring."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        hits = run_click_errors(
            lambda: GraphQueryService(store=store).search(
                selected_repo.id,
                query,
                types=[node_type] if node_type else None,
                languages=[language] if language else None,
                path_filters=[path_filter] if path_filter else None,
                name_filters=[name_filter] if name_filter else None,
                limit=limit,
            )
        )
        if as_json:
            echo_json(hits)
            return
        for hit in hits:
            node = hit.node
            location = f"{node.file_path}:{node.start_line}" if node.file_path else node.id
            click.echo(f"{hit.score:.2f}  {node.name} ({node.type})  {location}")

    @graph_group.command("callers")
    @click.argument("symbol")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--limit", default=20, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def graph_callers(
        ctx: click.Context,
        symbol: str,
        repo: str | None,
        repo_option: str | None,
        limit: int,
        as_json: bool,
    ) -> None:
        """List graph nodes that call or reference SYMBOL."""
        _echo_relationships(ctx, repo_option or repo, symbol, "callers", limit, as_json)

    @graph_group.command("callees")
    @click.argument("symbol")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--limit", default=20, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def graph_callees(
        ctx: click.Context,
        symbol: str,
        repo: str | None,
        repo_option: str | None,
        limit: int,
        as_json: bool,
    ) -> None:
        """List graph nodes called or referenced by SYMBOL."""
        _echo_relationships(ctx, repo_option or repo, symbol, "callees", limit, as_json)

    @graph_group.command("impact")
    @click.argument("symbol")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--depth", default=2, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def graph_impact(
        ctx: click.Context,
        symbol: str,
        repo: str | None,
        repo_option: str | None,
        depth: int,
        as_json: bool,
    ) -> None:
        """Show symbols potentially affected by changing SYMBOL."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        result = run_click_errors(lambda: GraphQueryService(store=store).impact(selected_repo.id, symbol, depth=depth))
        if as_json:
            echo_json(result)
            return
        click.echo(f"Impact: {len(result.nodes)} nodes, {len(result.edges)} edges")
        for node in sorted(result.nodes, key=lambda item: (item.file_path, item.start_line or 0, item.name))[:80]:
            location = f"{node.file_path}:{node.start_line}" if node.file_path else node.id
            click.echo(f"- {node.name} ({node.type}) {location}")

    @graph_group.command("explore")
    @click.argument("query")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--max-files", default=12, show_default=True, type=int)
    @click.option("--max-nodes", default=160, show_default=True, type=int)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def graph_explore(
        ctx: click.Context,
        query: str,
        repo: str | None,
        repo_option: str | None,
        max_files: int,
        max_nodes: int,
        as_json: bool,
    ) -> None:
        """Build an exploration context grouped by relevant source sections."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        result = run_click_errors(
            lambda: GraphQueryService(store=store).explore(
                selected_repo.id,
                query,
                max_files=max_files,
                max_nodes=max_nodes,
            )
        )
        if as_json:
            echo_json(result)
            return
        click.echo(result.text)

    @graph_group.command("affected")
    @click.argument("files", nargs=-1)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--stdin", "use_stdin", is_flag=True, help="Read changed files from stdin.")
    @click.option("--depth", default=5, show_default=True, type=int)
    @click.option("--test-glob", help="Custom glob used to identify test files.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def graph_affected(
        ctx: click.Context,
        files: tuple[str, ...],
        repo_option: str | None,
        use_stdin: bool,
        depth: int,
        test_glob: str | None,
        as_json: bool,
    ) -> None:
        """Find files, tests, and wiki pages affected by changed files."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option))
        changed_files = list(files)
        if use_stdin:
            changed_files.extend(
                line.strip() for line in click.get_text_stream("stdin").read().splitlines() if line.strip()
            )
        result = run_click_errors(
            lambda: GraphQueryService(store=store).affected(
                selected_repo.id,
                changed_files,
                depth=depth,
                test_glob=test_glob,
            )
        )
        if as_json:
            echo_json(result)
            return
        click.echo(f"Affected files: {len(result.affected_files)}")
        if result.affected_tests:
            click.echo("Affected tests:")
            for file_path in result.affected_tests:
                click.echo(f"- {file_path}")
        if result.affected_wiki_pages:
            click.echo("Affected wiki pages:")
            for slug in result.affected_wiki_pages:
                click.echo(f"- {slug}")

    @graph_group.command("status")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def graph_status(
        ctx: click.Context,
        repo: str | None,
        repo_option: str | None,
        as_json: bool,
    ) -> None:
        """Show graph index statistics."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        nodes, edges = run_click_errors(lambda: store.get_graph(selected_repo.id))
        payload = graph_status_payload(selected_repo.id, nodes, edges)
        if as_json:
            echo_json(payload)
            return
        click.echo(
            f"{payload['node_count']} nodes, {payload['edge_count']} edges, "
            f"{payload['file_count']} files"
        )
        nodes_by_type = cast(dict[str, int], payload["nodes_by_type"])
        echo_table(["type", "count"], [[key, value] for key, value in nodes_by_type.items()])


def _echo_relationships(
    ctx: click.Context,
    repo_selector: str | None,
    symbol: str,
    mode: str,
    limit: int,
    as_json: bool,
) -> None:
    store = store_from_context(ctx)
    selected_repo = run_click_errors(lambda: resolve_repo(store, repo_selector))
    service = GraphQueryService(store=store)
    relationships = run_click_errors(
        lambda: (
            service.callers(selected_repo.id, symbol, limit=limit)
            if mode == "callers"
            else service.callees(selected_repo.id, symbol, limit=limit)
        )
    )
    if as_json:
        echo_json(relationships)
        return
    for item in relationships:
        source = item.source
        target = item.target
        click.echo(
            f"{source.name} ({source.type}) -[{item.edge.type}]-> "
            f"{target.name} ({target.type})"
        )
