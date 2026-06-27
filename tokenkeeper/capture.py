"""Shared recording helpers for SDK and callback integrations."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from .ledger import CallRecord
from .pricing import calculate_cost

logger = logging.getLogger(__name__)

__all__ = ["Usage", "record_success", "record_error"]


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0


def record_success(
    *,
    ledger: Any,
    provider: str,
    model: str,
    usage: Usage,
    latency_ms: float,
    project: str,
    user: str,
) -> Optional[int]:
    """Record a successful model call without letting ledger failures escape."""
    if ledger is None:
        return None

    cost = calculate_cost(
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_tokens=usage.cached_tokens,
    )
    resolved_provider = cost.provider if cost.provider != "unknown" else provider
    call = CallRecord(
        timestamp=time.time(),
        project=project,
        user=user,
        provider=resolved_provider,
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_tokens=usage.cached_tokens,
        cost_usd=cost.cost_usd,
        cost_cny=cost.cost_cny,
        latency_ms=latency_ms,
        status="success",
        error=None,
    )
    return _safe_record(ledger, call)


def record_error(
    *,
    ledger: Any,
    provider: str,
    model: str,
    prompt_tokens: int,
    latency_ms: float,
    project: str,
    user: str,
    error: BaseException | str,
) -> Optional[int]:
    """Record a failed model call without letting ledger failures escape."""
    if ledger is None:
        return None

    call = CallRecord(
        timestamp=time.time(),
        project=project,
        user=user,
        provider=provider,
        model=model or "unknown",
        prompt_tokens=max(prompt_tokens, 0),
        completion_tokens=0,
        cached_tokens=0,
        cost_usd=0.0,
        cost_cny=0.0,
        latency_ms=latency_ms,
        status="error",
        error=str(error),
    )
    return _safe_record(ledger, call)


def _safe_record(ledger: Any, call: CallRecord) -> Optional[int]:
    try:
        rowid = ledger.record(call)
        return int(rowid) if rowid is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.error("failed to record tokenkeeper call: %s", exc)
        return None
