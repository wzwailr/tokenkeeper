"""Sync Hermes Desktop state.db usage into tokenkeeper."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from tokenkeeper.ledger import CallRecord, Ledger
from tokenkeeper.pricing import calculate_cost

logger = logging.getLogger(__name__)

__all__ = ["sync_hermes_to_tokenkeeper"]


def _get_hermes_db() -> Path:
    return Path.home() / "AppData" / "Local" / "hermes" / "state.db"


def sync_hermes_to_tokenkeeper(
    hermes_db_path: Optional[str] = None,
    tk_db_path: str = "~/.hermes/tokenkeeper.db",
) -> int:
    """Import or update Hermes session usage rows in the selected ledger.

    Returns the number of tokenkeeper rows inserted or updated.
    """
    hermes_db = Path(hermes_db_path) if hermes_db_path else _get_hermes_db()
    tk_db = Path(tk_db_path).expanduser()

    if not hermes_db.exists():
        logger.warning("Hermes DB not found: %s", hermes_db)
        return 0

    try:
        hermes_conn = sqlite3.connect(str(hermes_db))
        hermes_conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        logger.error("Cannot connect Hermes DB: %s", exc)
        return 0

    try:
        sessions = hermes_conn.execute(
            """
            SELECT
                id, title, billing_provider, model,
                input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens, reasoning_tokens,
                estimated_cost_usd, actual_cost_usd,
                started_at, ended_at
            FROM sessions
            WHERE (
                COALESCE(input_tokens, 0) > 0
                OR COALESCE(output_tokens, 0) > 0
                OR COALESCE(cache_read_tokens, 0) > 0
            )
            ORDER BY started_at DESC
            """
        ).fetchall()
    except sqlite3.Error as exc:
        logger.error("Cannot query Hermes sessions: %s", exc)
        hermes_conn.close()
        return 0
    finally:
        hermes_conn.close()

    changed = 0
    with Ledger(str(tk_db)) as ledger:
        existing = _load_existing_hermes_rows(tk_db)
        for session in sessions:
            session_id = str(session["id"])
            record = _session_to_record(session)
            existing_row = existing.get(session_id)

            if existing_row is not None:
                if _update_existing_hermes_record(tk_db, existing_row, record):
                    changed += 1
                continue

            if ledger.record(record) is not None:
                changed += 1

    logger.info("Hermes sync complete: %d inserted/updated", changed)
    return changed


def _load_existing_hermes_rows(tk_db: Path) -> dict[str, dict[str, Any]]:
    if not tk_db.exists():
        return {}

    conn = sqlite3.connect(str(tk_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM calls
            WHERE project = 'hermes' AND extra IS NOT NULL
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()

    existing: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_dict = dict(row)
        try:
            extra = json.loads(row_dict.get("extra") or "{}")
        except json.JSONDecodeError:
            continue
        session_id = extra.get("hermes_session_id")
        if isinstance(session_id, str):
            existing[session_id] = row_dict
    return existing


def _session_to_record(session: sqlite3.Row) -> CallRecord:
    provider = session["billing_provider"] or "unknown"
    model = session["model"] or "unknown"
    prompt_tokens = int(session["input_tokens"] or 0)
    completion_tokens = int(session["output_tokens"] or 0)
    cached_tokens = int(session["cache_read_tokens"] or 0)
    total_tokens = prompt_tokens + completion_tokens + cached_tokens

    cost_usd, cost_cny = _session_cost(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        actual_cost_usd=session["actual_cost_usd"],
        estimated_cost_usd=session["estimated_cost_usd"],
    )

    return CallRecord(
        timestamp=_session_timestamp(session["started_at"], session["ended_at"]),
        project="hermes",
        user="me",
        provider=str(provider),
        model=str(model),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cached_tokens=cached_tokens,
        cost_usd=cost_usd,
        cost_cny=cost_cny,
        latency_ms=0,
        status="success",
        extra={"hermes_session_id": str(session["id"]), "title": session["title"]},
    )


def _session_cost(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    actual_cost_usd: Any,
    estimated_cost_usd: Any,
) -> tuple[float, float]:
    hermes_cost = float(actual_cost_usd or estimated_cost_usd or 0)
    if hermes_cost > 0:
        return hermes_cost, round(hermes_cost * 7.2, 6)

    try:
        cost = calculate_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )
    except Exception:
        return 0.0, 0.0
    return cost.cost_usd, cost.cost_cny


def _session_timestamp(started_at: Any, ended_at: Any) -> float:
    timestamp = started_at or ended_at or time.time()
    if isinstance(timestamp, (int, float)):
        return float(timestamp)
    if isinstance(timestamp, str):
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return time.time()
    return time.time()


def _update_existing_hermes_record(
    tk_db: Path, row: dict[str, Any], record: CallRecord
) -> bool:
    extra_json = json.dumps(record.extra, ensure_ascii=False)
    values = {
        "timestamp": record.timestamp,
        "project": record.project,
        "user": record.user,
        "provider": record.provider,
        "model": record.model,
        "prompt_tokens": record.prompt_tokens,
        "completion_tokens": record.completion_tokens,
        "total_tokens": record.total_tokens,
        "cached_tokens": record.cached_tokens,
        "cost_usd": record.cost_usd,
        "cost_cny": record.cost_cny,
        "latency_ms": record.latency_ms,
        "status": record.status,
        "error": record.error,
        "extra": extra_json,
    }
    if _row_matches(row, values):
        return False

    conn = sqlite3.connect(str(tk_db))
    try:
        conn.execute(
            """
            UPDATE calls
            SET timestamp = ?,
                project = ?,
                "user" = ?,
                provider = ?,
                model = ?,
                prompt_tokens = ?,
                completion_tokens = ?,
                total_tokens = ?,
                cached_tokens = ?,
                cost_usd = ?,
                cost_cny = ?,
                latency_ms = ?,
                status = ?,
                error = ?,
                extra = ?
            WHERE id = ?
            """,
            (
                values["timestamp"],
                values["project"],
                values["user"],
                values["provider"],
                values["model"],
                values["prompt_tokens"],
                values["completion_tokens"],
                values["total_tokens"],
                values["cached_tokens"],
                values["cost_usd"],
                values["cost_cny"],
                values["latency_ms"],
                values["status"],
                values["error"],
                values["extra"],
                row["id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return True


def _row_matches(row: dict[str, Any], values: dict[str, Any]) -> bool:
    return all(row.get(key) == value for key, value in values.items())
