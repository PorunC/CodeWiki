from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


async def run_blocking(func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run blocking work in the default thread pool without pinning the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


class RepoWriteLockRegistry:
    def __init__(self, *, poll_interval_seconds: float = 0.05) -> None:
        self._poll_interval_seconds = poll_interval_seconds
        self._registry_lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @asynccontextmanager
    async def lock(self, repo_id: str) -> AsyncIterator[None]:
        lock = self._lock_for(repo_id)
        while not lock.acquire(blocking=False):
            await asyncio.sleep(self._poll_interval_seconds)
        try:
            yield
        finally:
            lock.release()

    def _lock_for(self, repo_id: str) -> threading.Lock:
        with self._registry_lock:
            lock = self._locks.get(repo_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[repo_id] = lock
            return lock


repo_write_locks = RepoWriteLockRegistry()


@asynccontextmanager
async def repo_write_lock(repo_id: str) -> AsyncIterator[None]:
    async with repo_write_locks.lock(repo_id):
        yield


__all__ = ["RepoWriteLockRegistry", "repo_write_lock", "run_blocking"]
