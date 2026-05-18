from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from backend.app.database import SQLiteStore
from backend.app.services.incremental.updater import IncrementalUpdater


@dataclass(frozen=True)
class WatchIterationResult:
    changed: bool
    affected_files: list[str]
    status: str
    run_id: str | None = None
    node_count: int = 0
    edge_count: int = 0


class IncrementalUpdateWatcher:
    """Polling watcher that keeps the graph and source chunks fresh.

    The project intentionally avoids an extra filesystem watcher dependency here. The
    watcher uses the existing incremental planner, which already combines git-diff
    candidates with content hashes, then debounces before running the update.
    """

    def __init__(
        self,
        *,
        store: SQLiteStore,
        updater: IncrementalUpdater | None = None,
    ) -> None:
        self.store = store
        self.updater = updater or IncrementalUpdater(store=store)

    def run(
        self,
        repo_id: str,
        *,
        interval_seconds: float = 2.0,
        debounce_seconds: float = 2.0,
        refresh_chunks: bool = True,
        on_iteration: Callable[[WatchIterationResult], None] | None = None,
    ) -> None:
        while True:
            result = self.tick(
                repo_id,
                debounce_seconds=debounce_seconds,
                refresh_chunks=refresh_chunks,
            )
            if on_iteration is not None:
                on_iteration(result)
            time.sleep(max(0.2, interval_seconds))

    def tick(
        self,
        repo_id: str,
        *,
        debounce_seconds: float = 2.0,
        refresh_chunks: bool = True,
    ) -> WatchIterationResult:
        plan = self.updater.plan(repo_id)
        if not plan.affected_files:
            return WatchIterationResult(changed=False, affected_files=[], status="idle")

        time.sleep(max(0.0, debounce_seconds))
        plan_after_debounce = self.updater.plan(repo_id)
        if not plan_after_debounce.affected_files:
            return WatchIterationResult(changed=False, affected_files=[], status="settled")

        result = self.updater.update(repo_id, refresh_chunks=refresh_chunks)
        return WatchIterationResult(
            changed=True,
            affected_files=result.plan.affected_files,
            status=result.status,
            run_id=result.run_id,
            node_count=result.node_count,
            edge_count=result.edge_count,
        )
