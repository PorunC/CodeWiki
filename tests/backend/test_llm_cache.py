from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.database import SQLiteStore
from backend.app.services.llm.gateway import LLMResult
from backend.app.services.llm.run_recorder import (
    LLMCallError,
    complete_with_cache,
    normalize_usage,
    unique_cache_key,
)
from backend.app.services.repo_scanner import RepoScanner


@pytest.mark.asyncio
async def test_complete_with_cache_reuses_recorded_llm_result(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    llm = _CountingLLM()
    messages = [{"role": "user", "content": "Explain the handler."}]
    payload = {"question": "Explain the handler.", "context": {"node_ids": ["node-1"]}}
    cache_key = unique_cache_key("qa", "trace-1", "question-1")

    first = await complete_with_cache(
        store,
        repo.id,
        llm=llm,
        task_type="qa",
        messages=messages,
        input_payload=payload,
        cache_key=cache_key,
        model_alias="qa",
        prompt_version="qa:v1",
    )
    second = await complete_with_cache(
        store,
        repo.id,
        llm=llm,
        task_type="qa",
        messages=messages,
        input_payload=payload,
        cache_key=cache_key,
        model_alias="qa",
        prompt_version="qa:v1",
    )

    assert llm.calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.run.cached is False
    assert second.run.cached is True
    assert second.result.content == first.result.content
    assert second.result.usage == {"prompt_tokens": 11, "completion_tokens": 7}
    runs = store.list_llm_runs(repo.id, task_type="qa")
    assert len(runs) == 2
    assert [run.cached for run in runs] == [True, False]


@pytest.mark.asyncio
async def test_complete_with_cache_misses_when_input_hash_changes(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    llm = _CountingLLM()
    messages = [{"role": "user", "content": "Explain the handler."}]
    cache_key = unique_cache_key("qa", "trace-1", "question-1")

    await complete_with_cache(
        store,
        repo.id,
        llm=llm,
        task_type="qa",
        messages=messages,
        input_payload={"question": "Explain the handler."},
        cache_key=cache_key,
        prompt_version="qa:v1",
    )
    second = await complete_with_cache(
        store,
        repo.id,
        llm=llm,
        task_type="qa",
        messages=messages,
        input_payload={"question": "Explain a different handler."},
        cache_key=cache_key,
        prompt_version="qa:v1",
    )

    assert llm.calls == 2
    assert second.cache_hit is False


@pytest.mark.asyncio
async def test_complete_with_cache_records_failed_llm_call(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    llm = _FailingLLM()
    messages = [{"role": "user", "content": "Explain the handler."}]

    with pytest.raises(LLMCallError) as exc_info:
        await complete_with_cache(
            store,
            repo.id,
            llm=llm,
            task_type="qa",
            messages=messages,
            input_payload={"question": "Explain the handler."},
            cache_key=unique_cache_key("qa", "trace-1", "question-1"),
            model_alias="qa",
            prompt_version="qa:v1",
        )

    runs = store.list_llm_runs(repo.id, task_type="qa")
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "error"
    assert run.cached is False
    assert run.response_content == ""
    assert run.model == "fake/qa"
    assert "RuntimeError: provider returned invalid JSON" in run.error
    assert "sk-test-secret" not in run.error
    assert exc_info.value.run_id == run.id


def test_unique_cache_key_is_stable() -> None:
    assert unique_cache_key("community_naming", "batch", 1) == "community_naming:batch:1"


@pytest.mark.asyncio
async def test_complete_with_cache_passes_provider_user_id_when_supported(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    llm = _ProviderUserLLM()

    await complete_with_cache(
        store,
        repo.id,
        llm=llm,
        task_type="qa",
        messages=[{"role": "user", "content": "Explain the handler."}],
        input_payload={"question": "Explain the handler."},
        cache_key=unique_cache_key("qa", "trace-1", "question-1"),
        provider_user_id="codewiki-custom-repo",
    )

    assert llm.provider_user_ids == ["codewiki-custom-repo"]


def test_normalize_usage_standardizes_provider_cache_tokens() -> None:
    usage = normalize_usage(
        {
            "input_tokens": 100,
            "output_tokens": 12,
            "prompt_tokens_details": {
                "cache_read_input_tokens": 70,
            },
        }
    )

    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 12
    assert usage["prompt_cache_hit_tokens"] == 70
    assert usage["prompt_cache_miss_tokens"] == 30
    assert usage["prompt_cache_hit_ratio"] == 0.7


class _FakeRouter:
    def profile_for(self, task_type: str) -> SimpleNamespace:
        assert task_type == "qa"
        return SimpleNamespace(model="fake/qa")


class _CountingLLM:
    router = _FakeRouter()

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        assert task_type == "qa"
        assert messages
        assert response_format is None
        self.calls += 1
        return LLMResult(
            content=f"cached answer {self.calls}",
            model="fake/qa",
            usage={"prompt_tokens": 11, "completion_tokens": 7},
        )


class _FailingLLM:
    router = _FakeRouter()

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        raise RuntimeError("provider returned invalid JSON for api_key=sk-test-secret-123456")


class _ProviderUserLLM:
    router = _FakeRouter()

    def __init__(self) -> None:
        self.provider_user_ids: list[str | None] = []

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
        provider_user_id: str | None = None,
    ) -> LLMResult:
        assert task_type == "qa"
        assert messages
        assert response_format is None
        self.provider_user_ids.append(provider_user_id)
        return LLMResult(content="answer", model="fake/qa", usage={})
