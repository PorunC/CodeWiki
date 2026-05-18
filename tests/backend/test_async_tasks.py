from __future__ import annotations

import asyncio
import threading

import pytest

from backend.app.services.async_tasks import RepoWriteLockRegistry, run_blocking


@pytest.mark.asyncio
async def test_run_blocking_leaves_event_loop_free() -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_task() -> str:
        started.set()
        release.wait(timeout=1)
        return "done"

    task = asyncio.create_task(run_blocking(blocking_task))
    while not started.is_set():
        await asyncio.sleep(0)

    await asyncio.sleep(0)
    assert not task.done()

    release.set()
    assert await task == "done"


@pytest.mark.asyncio
async def test_repo_write_locks_serialize_the_same_repo() -> None:
    locks = RepoWriteLockRegistry(poll_interval_seconds=0.001)
    entered_first = asyncio.Event()
    release_first = asyncio.Event()
    events: list[str] = []

    async def first_writer() -> None:
        async with locks.lock("repo-a"):
            events.append("first-enter")
            entered_first.set()
            await release_first.wait()
            events.append("first-exit")

    async def second_writer() -> None:
        await entered_first.wait()
        async with locks.lock("repo-a"):
            events.append("second-enter")

    first = asyncio.create_task(first_writer())
    second = asyncio.create_task(second_writer())

    await entered_first.wait()
    await asyncio.sleep(0.01)
    assert events == ["first-enter"]

    release_first.set()
    await asyncio.gather(first, second)
    assert events == ["first-enter", "first-exit", "second-enter"]


@pytest.mark.asyncio
async def test_repo_write_locks_allow_different_repos_to_overlap() -> None:
    locks = RepoWriteLockRegistry(poll_interval_seconds=0.001)
    entered_a = asyncio.Event()
    entered_b = asyncio.Event()

    async def writer_a() -> None:
        async with locks.lock("repo-a"):
            entered_a.set()
            await entered_b.wait()

    async def writer_b() -> None:
        async with locks.lock("repo-b"):
            entered_b.set()
            await entered_a.wait()

    await asyncio.wait_for(asyncio.gather(writer_a(), writer_b()), timeout=1)
