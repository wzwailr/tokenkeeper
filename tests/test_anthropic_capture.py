from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, AsyncIterator, Iterator

import pytest
from anthropic.resources.messages import AsyncMessages, Messages

from tokenkeeper.integrations import anthropic as anthropic_capture
from tokenkeeper.ledger import Ledger


class FakeGuardApi:
    def __init__(self, db_path: str) -> None:
        self._project = "anthropic-test"
        self._user = "tester"
        self._ledger = Ledger(db_path)

    def ledger(self) -> Ledger:
        return self._ledger

    def guard_instance(self) -> None:
        return None

    def close(self) -> None:
        self._ledger.close()


class FakeMessageStream:
    def __init__(self, final_message: Any) -> None:
        self._final_message = final_message

    def __iter__(self) -> Iterator[Any]:
        return iter([SimpleNamespace(type="message_start")])

    def get_final_message(self) -> Any:
        return self._final_message


class FakeStreamManager:
    def __init__(self, stream: FakeMessageStream) -> None:
        self._stream = stream

    def __enter__(self) -> FakeMessageStream:
        return self._stream

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


class FakeAsyncMessageStream:
    def __init__(self, final_message: Any) -> None:
        self._final_message = final_message

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        yield SimpleNamespace(type="message_start")

    async def get_final_message(self) -> Any:
        return self._final_message


class FakeAsyncStreamManager:
    def __init__(self, stream: FakeAsyncMessageStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> FakeAsyncMessageStream:
        return self._stream

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


@pytest.fixture(autouse=True)
def cleanup_anthropic_patch() -> Iterator[None]:
    anthropic_capture.uninstall()
    yield
    anthropic_capture.uninstall()


@pytest.fixture
def guard_api(tmp_path: Any) -> Iterator[FakeGuardApi]:
    api = FakeGuardApi(str(tmp_path / "tokenkeeper.db"))
    yield api
    api.close()


def _usage(input_tokens: int, output_tokens: int, cached: int = 0) -> Any:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cached,
    )


def _message(model: str, input_tokens: int = 100, output_tokens: int = 50) -> Any:
    return SimpleNamespace(model=model, usage=_usage(input_tokens, output_tokens))


def test_sync_create_class_patch_records_success(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _message(kwargs["model"], input_tokens=100, output_tokens=50)

    monkeypatch.setattr(Messages, "create", fake_create)

    anthropic_capture.install(guard_api)
    Messages.create(
        object(),
        model="claude-sonnet-4",
        max_tokens=32,
        messages=[{"role": "user", "content": "hello"}],
    )

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].provider == "anthropic"
    assert records[0].model == "claude-sonnet-4"
    assert records[0].prompt_tokens == 100
    assert records[0].completion_tokens == 50


def test_async_create_class_patch_records_success(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_sync_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _message(kwargs["model"])

    async def fake_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _message(kwargs["model"], input_tokens=80, output_tokens=20)

    monkeypatch.setattr(Messages, "create", fake_sync_create)
    monkeypatch.setattr(AsyncMessages, "create", fake_async_create)

    anthropic_capture.install(guard_api)
    asyncio.run(
        AsyncMessages.create(
            object(),
            model="claude-sonnet-4",
            max_tokens=32,
            messages=[{"role": "user", "content": "hello"}],
        )
    )

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].prompt_tokens == 80
    assert records[0].completion_tokens == 20


def test_sync_stream_manager_records_on_context_exit(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_stream(self: Any, *args: Any, **kwargs: Any) -> Any:
        return FakeStreamManager(
            FakeMessageStream(
                _message(kwargs["model"], input_tokens=120, output_tokens=40)
            )
        )

    monkeypatch.setattr(Messages, "stream", fake_stream)

    anthropic_capture.install(guard_api)
    manager = Messages.stream(
        object(),
        model="claude-sonnet-4",
        max_tokens=32,
        messages=[{"role": "user", "content": "hello"}],
    )
    with manager as stream:
        assert len(list(stream)) == 1

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].prompt_tokens == 120
    assert records[0].completion_tokens == 40


def test_async_stream_manager_records_on_context_exit(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_stream(self: Any, *args: Any, **kwargs: Any) -> Any:
        return FakeAsyncStreamManager(
            FakeAsyncMessageStream(
                _message(kwargs["model"], input_tokens=90, output_tokens=30)
            )
        )

    async def run_capture() -> None:
        manager = AsyncMessages.stream(
            object(),
            model="claude-sonnet-4",
            max_tokens=32,
            messages=[{"role": "user", "content": "hello"}],
        )
        async with manager as stream:
            events = [event async for event in stream]
        assert len(events) == 1

    monkeypatch.setattr(AsyncMessages, "stream", fake_stream)

    anthropic_capture.install(guard_api)
    asyncio.run(run_capture())

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].prompt_tokens == 90
    assert records[0].completion_tokens == 30


def test_error_path_records_and_reraises(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    monkeypatch.setattr(Messages, "create", fake_create)

    anthropic_capture.install(guard_api)
    with pytest.raises(RuntimeError, match="provider down"):
        Messages.create(
            object(),
            model="claude-sonnet-4",
            max_tokens=32,
            messages=[{"role": "user", "content": "hello"}],
        )

    records = guard_api.ledger().query(limit=10)
    assert len(records) == 1
    assert records[0].status == "error"
    assert records[0].error == "provider down"


def test_uninstall_restores_all_class_methods(
    monkeypatch: pytest.MonkeyPatch, guard_api: FakeGuardApi
) -> None:
    def fake_sync_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _message(kwargs["model"])

    async def fake_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        return _message(kwargs["model"])

    def fake_sync_stream(self: Any, *args: Any, **kwargs: Any) -> Any:
        return FakeStreamManager(FakeMessageStream(_message(kwargs["model"])))

    def fake_async_stream(self: Any, *args: Any, **kwargs: Any) -> Any:
        return FakeAsyncStreamManager(FakeAsyncMessageStream(_message(kwargs["model"])))

    monkeypatch.setattr(Messages, "create", fake_sync_create)
    monkeypatch.setattr(AsyncMessages, "create", fake_async_create)
    monkeypatch.setattr(Messages, "stream", fake_sync_stream)
    monkeypatch.setattr(AsyncMessages, "stream", fake_async_stream)

    anthropic_capture.install(guard_api)
    assert Messages.create is not fake_sync_create
    assert AsyncMessages.create is not fake_async_create
    assert Messages.stream is not fake_sync_stream
    assert AsyncMessages.stream is not fake_async_stream

    anthropic_capture.uninstall()

    assert Messages.create is fake_sync_create
    assert AsyncMessages.create is fake_async_create
    assert Messages.stream is fake_sync_stream
    assert AsyncMessages.stream is fake_async_stream
