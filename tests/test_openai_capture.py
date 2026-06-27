from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, AsyncIterator, Iterator

import pytest
from openai.resources.chat.completions import AsyncCompletions, Completions

from tokenkeeper.integrations import openai_compat
from tokenkeeper.ledger import Ledger


class FakeGuardApi:
    def __init__(self, db_path: str) -> None:
        self._project = "sdk-test"
        self._user = "tester"
        self._ledger = Ledger(db_path)

    def ledger(self) -> Ledger:
        return self._ledger

    def guard_instance(self) -> None:
        return None

    def close(self) -> None:
        self._ledger.close()


class FakeAsyncStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        for chunk in self._chunks:
            yield chunk


@pytest.fixture(autouse=True)
def cleanup_openai_patch() -> Iterator[None]:
    openai_compat.uninstall()
    yield
    openai_compat.uninstall()


@pytest.fixture
def guard_api(tmp_path: Any) -> Iterator[FakeGuardApi]:
    api = FakeGuardApi(str(tmp_path / "tokenkeeper.db"))
    yield api
    api.close()


def _usage(prompt: int, completion: int, cached: int = 0) -> Any:
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
    )


def _response(model: str, prompt: int = 100, completion: int = 50) -> Any:
    return SimpleNamespace(model=model, usage=_usage(prompt, completion))


def _chunk(model: str, usage: Any | None = None) -> Any:
    return SimpleNamespace(model=model, usage=usage, choices=[])


def test_sync_create_records_openai_compatible_provider(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _response(kwargs["model"], prompt=100, completion=50)

    monkeypatch.setattr(Completions, "create", fake_create)

    openai_compat.install(guard_api)
    Completions.create(
        object(),
        model="deepseek-chat",
        messages=[{"role": "user", "content": "hello"}],
    )

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].provider == "deepseek"
    assert records[0].model == "deepseek-chat"
    assert records[0].prompt_tokens == 100
    assert records[0].completion_tokens == 50


def test_async_create_records_success(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_sync_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _response(kwargs["model"])

    async def fake_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _response(kwargs["model"], prompt=75, completion=25)

    monkeypatch.setattr(Completions, "create", fake_sync_create)
    monkeypatch.setattr(AsyncCompletions, "create", fake_async_create)

    openai_compat.install(guard_api)
    resp = asyncio.run(
        AsyncCompletions.create(
            object(),
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
        )
    )

    assert resp.model == "gpt-4o-mini"
    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].provider == "openai"
    assert records[0].prompt_tokens == 75
    assert records[0].completion_tokens == 25


def test_sync_stream_records_when_iteration_finishes(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        assert kwargs["stream_options"]["include_usage"] is True
        return iter(
            [
                _chunk(kwargs["model"]),
                _chunk(kwargs["model"], _usage(prompt=120, completion=80, cached=20)),
            ]
        )

    monkeypatch.setattr(Completions, "create", fake_create)

    openai_compat.install(guard_api)
    stream = Completions.create(
        object(),
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    assert len(list(stream)) == 2

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].prompt_tokens == 120
    assert records[0].completion_tokens == 80
    assert records[0].cached_tokens == 20


def test_async_stream_records_when_iteration_finishes(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_sync_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _response(kwargs["model"])

    async def fake_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        assert kwargs["stream_options"]["include_usage"] is True
        return FakeAsyncStream(
            [
                _chunk(kwargs["model"]),
                _chunk(kwargs["model"], _usage(prompt=90, completion=30, cached=10)),
            ]
        )

    async def run_capture() -> list[Any]:
        stream = await AsyncCompletions.create(
            object(),
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
        )
        return [chunk async for chunk in stream]

    monkeypatch.setattr(Completions, "create", fake_sync_create)
    monkeypatch.setattr(AsyncCompletions, "create", fake_async_create)

    openai_compat.install(guard_api)
    assert len(asyncio.run(run_capture())) == 2

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].prompt_tokens == 90
    assert records[0].completion_tokens == 30
    assert records[0].cached_tokens == 10


def test_error_path_records_and_reraises(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(Completions, "create", fake_create)
    monkeypatch.setattr(openai_compat.time, "sleep", lambda seconds: None)

    openai_compat.install(guard_api)
    with pytest.raises(RuntimeError, match="provider down"):
        Completions.create(
            object(),
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].status == "error"
    assert records[0].error == "provider down"


def test_uninstall_restores_sync_and_async_methods(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_sync_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _response(kwargs["model"])

    async def fake_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _response(kwargs["model"])

    monkeypatch.setattr(Completions, "create", fake_sync_create)
    monkeypatch.setattr(AsyncCompletions, "create", fake_async_create)

    openai_compat.install(guard_api)
    assert Completions.create is not fake_sync_create
    assert AsyncCompletions.create is not fake_async_create

    openai_compat.uninstall()

    assert Completions.create is fake_sync_create
    assert AsyncCompletions.create is fake_async_create
