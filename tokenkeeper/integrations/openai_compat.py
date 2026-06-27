"""OpenAI and OpenAI-compatible SDK capture."""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator, Iterator, Optional

from tokenkeeper.capture import Usage, record_error, record_success
from tokenkeeper.guard import BudgetExceededError
from tokenkeeper.pricing import calculate_cost

__all__ = ["install", "uninstall"]

logger = logging.getLogger(__name__)

_original_create: Optional[Any] = None
_original_async_create: Optional[Any] = None
_guard_api: Optional[Any] = None


def install(guard_api: Any) -> None:
    """Patch OpenAI chat completions sync and async create methods."""
    global _guard_api, _original_async_create, _original_create

    if _original_create is not None or _original_async_create is not None:
        return

    try:
        from openai.resources.chat import completions as chat_completions
    except ImportError as exc:
        logger.error("openai package is not installed: %s", exc)
        raise

    _guard_api = guard_api
    _original_create = chat_completions.Completions.create
    _original_async_create = chat_completions.AsyncCompletions.create
    chat_completions.Completions.create = _wrap_create  # type: ignore[method-assign]
    chat_completions.AsyncCompletions.create = _wrap_async_create  # type: ignore[method-assign]


def uninstall() -> None:
    """Restore OpenAI SDK methods patched by :func:`install`."""
    global _guard_api, _original_async_create, _original_create

    if _original_create is None and _original_async_create is None:
        return

    try:
        from openai.resources.chat import completions as chat_completions

        if _original_create is not None:
            chat_completions.Completions.create = _original_create  # type: ignore[method-assign]
        if _original_async_create is not None:
            chat_completions.AsyncCompletions.create = _original_async_create  # type: ignore[method-assign]
    except ImportError:
        pass
    finally:
        _original_create = None
        _original_async_create = None
        _guard_api = None


def _wrap_create(self: Any, *args: Any, **kwargs: Any) -> Any:
    if _guard_api is None or _original_create is None:
        raise RuntimeError("tokenkeeper is not initialized")

    model = kwargs.get("model", "unknown")
    project, user, ledger = _context()
    estimated_prompt_tokens = _estimate_input_tokens(kwargs.get("messages", []))
    _check_budget(model, estimated_prompt_tokens, project, user)
    _ensure_stream_usage(kwargs)

    t0 = time.time()
    try:
        response = _original_create(self, *args, **kwargs)
    except Exception as exc:
        record_error(
            ledger=ledger,
            provider="openai",
            model=model,
            prompt_tokens=estimated_prompt_tokens,
            latency_ms=_elapsed_ms(t0),
            project=project,
            user=user,
            error=exc,
        )
        raise

    if kwargs.get("stream", False):
        return _wrap_stream(response, model, project, user, t0, ledger)

    actual_model = _extract_model(response) or model
    record_success(
        ledger=ledger,
        provider="openai",
        model=actual_model,
        usage=Usage(*_extract_usage(response)),
        latency_ms=_elapsed_ms(t0),
        project=project,
        user=user,
    )
    return response


async def _wrap_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
    if _guard_api is None or _original_async_create is None:
        raise RuntimeError("tokenkeeper is not initialized")

    model = kwargs.get("model", "unknown")
    project, user, ledger = _context()
    estimated_prompt_tokens = _estimate_input_tokens(kwargs.get("messages", []))
    _check_budget(model, estimated_prompt_tokens, project, user)
    _ensure_stream_usage(kwargs)

    t0 = time.time()
    try:
        response = await _original_async_create(self, *args, **kwargs)
    except Exception as exc:
        record_error(
            ledger=ledger,
            provider="openai",
            model=model,
            prompt_tokens=estimated_prompt_tokens,
            latency_ms=_elapsed_ms(t0),
            project=project,
            user=user,
            error=exc,
        )
        raise

    if kwargs.get("stream", False):
        return _wrap_async_stream(response, model, project, user, t0, ledger)

    actual_model = _extract_model(response) or model
    record_success(
        ledger=ledger,
        provider="openai",
        model=actual_model,
        usage=Usage(*_extract_usage(response)),
        latency_ms=_elapsed_ms(t0),
        project=project,
        user=user,
    )
    return response


def _wrap_stream(
    stream: Any,
    requested_model: str,
    project: str,
    user: str,
    t0: float,
    ledger: Any,
) -> Iterator[Any]:
    final_usage = None
    final_model = requested_model
    error: Optional[BaseException] = None

    try:
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                final_usage = usage
            chunk_model = getattr(chunk, "model", None)
            if chunk_model:
                final_model = chunk_model
            yield chunk
    except Exception as exc:
        error = exc
        raise
    finally:
        _record_stream_result(
            ledger=ledger,
            provider="openai",
            requested_model=requested_model,
            actual_model=final_model,
            usage=final_usage,
            project=project,
            user=user,
            t0=t0,
            error=error,
            usage_extractor=_extract_usage_object,
        )


async def _wrap_async_stream(
    stream: Any,
    requested_model: str,
    project: str,
    user: str,
    t0: float,
    ledger: Any,
) -> AsyncIterator[Any]:
    final_usage = None
    final_model = requested_model
    error: Optional[BaseException] = None

    try:
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                final_usage = usage
            chunk_model = getattr(chunk, "model", None)
            if chunk_model:
                final_model = chunk_model
            yield chunk
    except Exception as exc:
        error = exc
        raise
    finally:
        _record_stream_result(
            ledger=ledger,
            provider="openai",
            requested_model=requested_model,
            actual_model=final_model,
            usage=final_usage,
            project=project,
            user=user,
            t0=t0,
            error=error,
            usage_extractor=_extract_usage_object,
        )


def _record_stream_result(
    *,
    ledger: Any,
    provider: str,
    requested_model: str,
    actual_model: str,
    usage: Any,
    project: str,
    user: str,
    t0: float,
    error: Optional[BaseException],
    usage_extractor: Any,
) -> None:
    if error is not None:
        record_error(
            ledger=ledger,
            provider=provider,
            model=requested_model,
            prompt_tokens=0,
            latency_ms=_elapsed_ms(t0),
            project=project,
            user=user,
            error=error,
        )
        return

    record_success(
        ledger=ledger,
        provider=provider,
        model=actual_model or requested_model,
        usage=usage_extractor(usage),
        latency_ms=_elapsed_ms(t0),
        project=project,
        user=user,
    )


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


def _ensure_stream_usage(kwargs: dict[str, Any]) -> None:
    if not kwargs.get("stream", False):
        return
    options = kwargs.get("stream_options") or {}
    if "include_usage" not in options:
        kwargs["stream_options"] = {**options, "include_usage": True}


def _elapsed_ms(t0: float) -> float:
    return (time.time() - t0) * 1000


def _estimate_input_tokens(messages: list[Any]) -> int:
    total_chars = 0
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
    return _extract_usage_tuple(getattr(resp, "usage", None))


def _extract_usage_object(usage: Any) -> Usage:
    return Usage(*_extract_usage_tuple(usage))


def _extract_usage_tuple(usage: Any) -> tuple[int, int, int]:
    if usage is None:
        return 0, 0, 0
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    cached_tokens = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached_tokens = getattr(details, "cached_tokens", 0) or 0
    return int(prompt_tokens), int(completion_tokens), int(cached_tokens)


def _extract_model(resp: Any) -> Optional[str]:
    return getattr(resp, "model", None)
