"""Anthropic SDK capture."""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Optional

from tokenkeeper.capture import Usage, record_error, record_success
from tokenkeeper.guard import BudgetExceededError
from tokenkeeper.pricing import calculate_cost

__all__ = ["install", "uninstall"]

logger = logging.getLogger(__name__)

_original_anthropic_create: Optional[Any] = None
_original_anthropic_async_create: Optional[Any] = None
_original_anthropic_stream: Optional[Any] = None
_original_anthropic_async_stream: Optional[Any] = None
_guard_api: Optional[Any] = None


def install(guard_api: Any) -> None:
    """Patch Anthropic messages create and stream class methods."""
    global _guard_api
    global _original_anthropic_async_create
    global _original_anthropic_async_stream
    global _original_anthropic_create
    global _original_anthropic_stream

    if guard_api is None:
        logger.warning("anthropic patch skipped because guard_api is missing")
        return
    if _original_anthropic_create is not None:
        return

    try:
        from anthropic.resources.messages import AsyncMessages, Messages
    except ImportError as exc:
        logger.error("anthropic package is not installed: %s", exc)
        raise

    _guard_api = guard_api
    _original_anthropic_create = Messages.create
    _original_anthropic_async_create = AsyncMessages.create
    _original_anthropic_stream = getattr(Messages, "stream", None)
    _original_anthropic_async_stream = getattr(AsyncMessages, "stream", None)

    Messages.create = _wrap_create  # type: ignore[method-assign]
    AsyncMessages.create = _wrap_async_create  # type: ignore[method-assign]
    if _original_anthropic_stream is not None:
        Messages.stream = _wrap_stream_manager  # type: ignore[method-assign]
    if _original_anthropic_async_stream is not None:
        AsyncMessages.stream = _wrap_async_stream_manager  # type: ignore[method-assign]


def uninstall() -> None:
    """Restore Anthropic SDK methods patched by :func:`install`."""
    global _guard_api
    global _original_anthropic_async_create
    global _original_anthropic_async_stream
    global _original_anthropic_create
    global _original_anthropic_stream

    if _original_anthropic_create is None:
        return

    try:
        from anthropic.resources.messages import AsyncMessages, Messages

        Messages.create = _original_anthropic_create  # type: ignore[method-assign]
        if _original_anthropic_async_create is not None:
            AsyncMessages.create = _original_anthropic_async_create  # type: ignore[method-assign]
        if _original_anthropic_stream is not None:
            Messages.stream = _original_anthropic_stream  # type: ignore[method-assign]
        if _original_anthropic_async_stream is not None:
            AsyncMessages.stream = _original_anthropic_async_stream  # type: ignore[method-assign]
    except ImportError:
        pass
    finally:
        _original_anthropic_create = None
        _original_anthropic_async_create = None
        _original_anthropic_stream = None
        _original_anthropic_async_stream = None
        _guard_api = None


def _wrap_create(self: Any, *args: Any, **kwargs: Any) -> Any:
    if _guard_api is None or _original_anthropic_create is None:
        raise RuntimeError("tokenkeeper is not initialized")

    model = kwargs.get("model", "unknown")
    project, user, ledger = _context()
    estimated_prompt_tokens = _estimate_input_tokens(
        kwargs.get("messages", []), kwargs.get("system")
    )
    _check_budget(model, estimated_prompt_tokens, project, user)

    t0 = time.time()
    try:
        response = _original_anthropic_create(self, *args, **kwargs)
    except Exception as exc:
        record_error(
            ledger=ledger,
            provider="anthropic",
            model=model,
            prompt_tokens=estimated_prompt_tokens,
            latency_ms=_elapsed_ms(t0),
            project=project,
            user=user,
            error=exc,
        )
        raise

    if kwargs.get("stream", False):
        return _wrap_raw_stream(response, model, project, user, t0, ledger)

    actual_model = _extract_model(response) or model
    record_success(
        ledger=ledger,
        provider="anthropic",
        model=actual_model,
        usage=Usage(*_extract_usage(response)),
        latency_ms=_elapsed_ms(t0),
        project=project,
        user=user,
    )
    return response


async def _wrap_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
    if _guard_api is None or _original_anthropic_async_create is None:
        raise RuntimeError("tokenkeeper is not initialized")

    model = kwargs.get("model", "unknown")
    project, user, ledger = _context()
    estimated_prompt_tokens = _estimate_input_tokens(
        kwargs.get("messages", []), kwargs.get("system")
    )
    _check_budget(model, estimated_prompt_tokens, project, user)

    t0 = time.time()
    try:
        response = await _original_anthropic_async_create(self, *args, **kwargs)
    except Exception as exc:
        record_error(
            ledger=ledger,
            provider="anthropic",
            model=model,
            prompt_tokens=estimated_prompt_tokens,
            latency_ms=_elapsed_ms(t0),
            project=project,
            user=user,
            error=exc,
        )
        raise

    if kwargs.get("stream", False):
        return _wrap_async_raw_stream(response, model, project, user, t0, ledger)

    actual_model = _extract_model(response) or model
    record_success(
        ledger=ledger,
        provider="anthropic",
        model=actual_model,
        usage=Usage(*_extract_usage(response)),
        latency_ms=_elapsed_ms(t0),
        project=project,
        user=user,
    )
    return response


def _wrap_stream_manager(self: Any, *args: Any, **kwargs: Any) -> Any:
    if _guard_api is None or _original_anthropic_stream is None:
        raise RuntimeError("tokenkeeper is not initialized")

    model = kwargs.get("model", "unknown")
    project, user, ledger = _context()
    estimated_prompt_tokens = _estimate_input_tokens(
        kwargs.get("messages", []), kwargs.get("system")
    )
    _check_budget(model, estimated_prompt_tokens, project, user)

    t0 = time.time()
    try:
        manager = _original_anthropic_stream(self, *args, **kwargs)
    except Exception as exc:
        record_error(
            ledger=ledger,
            provider="anthropic",
            model=model,
            prompt_tokens=estimated_prompt_tokens,
            latency_ms=_elapsed_ms(t0),
            project=project,
            user=user,
            error=exc,
        )
        raise

    return _SyncStreamManagerCapture(manager, model, project, user, t0, ledger)


def _wrap_async_stream_manager(self: Any, *args: Any, **kwargs: Any) -> Any:
    if _guard_api is None or _original_anthropic_async_stream is None:
        raise RuntimeError("tokenkeeper is not initialized")

    model = kwargs.get("model", "unknown")
    project, user, ledger = _context()
    estimated_prompt_tokens = _estimate_input_tokens(
        kwargs.get("messages", []), kwargs.get("system")
    )
    _check_budget(model, estimated_prompt_tokens, project, user)

    t0 = time.time()
    try:
        manager = _original_anthropic_async_stream(self, *args, **kwargs)
    except Exception as exc:
        record_error(
            ledger=ledger,
            provider="anthropic",
            model=model,
            prompt_tokens=estimated_prompt_tokens,
            latency_ms=_elapsed_ms(t0),
            project=project,
            user=user,
            error=exc,
        )
        raise

    return _AsyncStreamManagerCapture(manager, model, project, user, t0, ledger)


class _SyncStreamManagerCapture:
    def __init__(
        self,
        manager: Any,
        requested_model: str,
        project: str,
        user: str,
        t0: float,
        ledger: Any,
    ) -> None:
        self._manager = manager
        self._requested_model = requested_model
        self._project = project
        self._user = user
        self._t0 = t0
        self._ledger = ledger
        self._stream: Any = None

    def __enter__(self) -> Any:
        self._stream = self._manager.__enter__()
        return self._stream

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        manager_result = None
        manager_error: Optional[BaseException] = None
        try:
            manager_result = self._manager.__exit__(exc_type, exc, tb)
        except Exception as manager_exc:
            manager_error = manager_exc
            raise
        finally:
            error = exc or manager_error
            if error is not None:
                _record_error_result(
                    self._ledger,
                    "anthropic",
                    self._requested_model,
                    self._project,
                    self._user,
                    self._t0,
                    error,
                )
            else:
                message = _get_final_message(self._stream, self._manager)
                _record_success_result(
                    self._ledger,
                    "anthropic",
                    self._requested_model,
                    message,
                    self._project,
                    self._user,
                    self._t0,
                )
        return manager_result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)


class _AsyncStreamManagerCapture:
    def __init__(
        self,
        manager: Any,
        requested_model: str,
        project: str,
        user: str,
        t0: float,
        ledger: Any,
    ) -> None:
        self._manager = manager
        self._requested_model = requested_model
        self._project = project
        self._user = user
        self._t0 = t0
        self._ledger = ledger
        self._stream: Any = None

    async def __aenter__(self) -> Any:
        self._stream = await _maybe_await(self._manager.__aenter__())
        return self._stream

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        manager_result = None
        manager_error: Optional[BaseException] = None
        try:
            manager_result = await _maybe_await(
                self._manager.__aexit__(exc_type, exc, tb)
            )
        except Exception as manager_exc:
            manager_error = manager_exc
            raise
        finally:
            error = exc or manager_error
            if error is not None:
                _record_error_result(
                    self._ledger,
                    "anthropic",
                    self._requested_model,
                    self._project,
                    self._user,
                    self._t0,
                    error,
                )
            else:
                message = await _get_async_final_message(self._stream, self._manager)
                _record_success_result(
                    self._ledger,
                    "anthropic",
                    self._requested_model,
                    message,
                    self._project,
                    self._user,
                    self._t0,
                )
        return manager_result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)


def _wrap_raw_stream(
    stream: Any,
    requested_model: str,
    project: str,
    user: str,
    t0: float,
    ledger: Any,
) -> Any:
    error: Optional[BaseException] = None
    final_message = None

    def iterator() -> Any:
        nonlocal error, final_message
        try:
            for event in stream:
                final_message = _message_from_event(event) or final_message
                yield event
        except Exception as exc:
            error = exc
            raise
        finally:
            if error is not None:
                _record_error_result(
                    ledger, "anthropic", requested_model, project, user, t0, error
                )
            else:
                message = final_message or _get_final_message(stream, stream)
                _record_success_result(
                    ledger,
                    "anthropic",
                    requested_model,
                    message,
                    project,
                    user,
                    t0,
                )

    return iterator()


async def _wrap_async_raw_stream(
    stream: Any,
    requested_model: str,
    project: str,
    user: str,
    t0: float,
    ledger: Any,
) -> Any:
    error: Optional[BaseException] = None
    final_message = None

    async def iterator() -> Any:
        nonlocal error, final_message
        try:
            async for event in stream:
                final_message = _message_from_event(event) or final_message
                yield event
        except Exception as exc:
            error = exc
            raise
        finally:
            if error is not None:
                _record_error_result(
                    ledger, "anthropic", requested_model, project, user, t0, error
                )
            else:
                message = final_message or await _get_async_final_message(
                    stream, stream
                )
                _record_success_result(
                    ledger,
                    "anthropic",
                    requested_model,
                    message,
                    project,
                    user,
                    t0,
                )

    return iterator()


def _record_success_result(
    ledger: Any,
    provider: str,
    requested_model: str,
    message: Any,
    project: str,
    user: str,
    t0: float,
) -> None:
    actual_model = _extract_model(message) or requested_model
    record_success(
        ledger=ledger,
        provider=provider,
        model=actual_model,
        usage=Usage(*_extract_usage(message)),
        latency_ms=_elapsed_ms(t0),
        project=project,
        user=user,
    )


def _record_error_result(
    ledger: Any,
    provider: str,
    model: str,
    project: str,
    user: str,
    t0: float,
    error: BaseException,
) -> None:
    record_error(
        ledger=ledger,
        provider=provider,
        model=model,
        prompt_tokens=0,
        latency_ms=_elapsed_ms(t0),
        project=project,
        user=user,
        error=error,
    )


def _get_final_message(stream: Any, manager: Any) -> Any:
    for target in (stream, manager):
        method = getattr(target, "get_final_message", None)
        if method is not None:
            return method()
    return None


async def _get_async_final_message(stream: Any, manager: Any) -> Any:
    for target in (stream, manager):
        method = getattr(target, "get_final_message", None)
        if method is not None:
            return await _maybe_await(method())
    return None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _message_from_event(event: Any) -> Any:
    return getattr(event, "message", None)


def _context() -> tuple[str, str, Any]:
    if _guard_api is None:
        return "default", "default", None
    return (
        getattr(_guard_api, "_project", "default"),
        getattr(_guard_api, "_user", "default"),
        _guard_api.ledger(),
    )


def _check_budget(model: str, prompt_tokens: int, project: str, user: str) -> None:
    if _guard_api is None:
        return
    guard_instance = _guard_api.guard_instance()
    if guard_instance is None:
        return
    try:
        estimated_cost = calculate_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=500,
            cached_tokens=0,
        ).cost_usd
        guard_instance.check(
            estimated_cost=estimated_cost,
            project=project,
            user=user,
        )
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("guard check failed; allowing call: %s", exc)


def _elapsed_ms(t0: float) -> float:
    return (time.time() - t0) * 1000


def _estimate_input_tokens(messages: list[Any], system: Any = None) -> int:
    total_chars = 0
    if isinstance(system, str):
        total_chars += len(system)
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                total_chars += len(block.get("text", ""))

    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total_chars += len(part.get("text", ""))
    return total_chars // 3


def _extract_usage(resp: Any) -> tuple[int, int, int]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return 0, 0, 0
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cached_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
    return int(input_tokens), int(output_tokens), int(cached_tokens)


def _extract_model(resp: Any) -> Optional[str]:
    return getattr(resp, "model", None)
