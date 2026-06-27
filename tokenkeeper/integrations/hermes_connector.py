"""Hermes 桌面应用连接器 — 从 Hermes 的 state.db 读取 token 数据写入 tokenkeeper。

用法::

    from tokenkeeper.integrations.hermes import sync_hermes_to_tokenkeeper
    sync_hermes_to_tokenkeeper()

每次调用会增量同步 Hermes session 数据到 tokenkeeper 账本。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from tokenkeeper.ledger import CallRecord

logger = logging.getLogger(__name__)

__all__ = ["sync_hermes_to_tokenkeeper"]


def _get_hermes_db() -> Path:
    """获取 Hermes state.db 路径。"""
    return Path.home() / "AppData" / "Local" / "hermes" / "state.db"


def sync_hermes_to_tokenkeeper(
    hermes_db_path: Optional[str] = None,
    tk_db_path: str = "~/.hermes/tokenkeeper.db",
) -> int:
    """将 Hermes 的 token 数据同步到 tokenkeeper。

    增量同步：只导入 tokenkeeper 中不存在的 session。

    Args:
        hermes_db_path: Hermes state.db 路径（None = 自动检测）
        tk_db_path: tokenkeeper DB 路径

    Returns:
        本次同步的记录数
    """
    hermes_db = Path(hermes_db_path) if hermes_db_path else _get_hermes_db()
    tk_db = Path(tk_db_path).expanduser()

    if not hermes_db.exists():
        logger.warning("Hermes DB 未找到: %s", hermes_db)
        return 0

    try:
        hermes_conn = sqlite3.connect(str(hermes_db))
        hermes_conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        logger.error("无法连接 Hermes DB: %s", e)
        return 0

    # 导入 tokenkeeper
    from tokenkeeper.core import guard as api
    from tokenkeeper.ledger import Ledger

    # 确保 tokenkeeper 已安装
    if not _ensure_tk_installed(str(tk_db)):
        hermes_conn.close()
        return 0

    ledger = api.ledger()

    # 查 tokenkeeper 已有的 session ID（避免重复导入）
    existing = set()
    try:
        tk_conn = sqlite3.connect(str(tk_db))
        tk_conn.row_factory = sqlite3.Row
        rows = tk_conn.execute(
            "SELECT DISTINCT extra FROM calls WHERE extra IS NOT NULL"
        ).fetchall()
        for row in rows:
            try:
                import json
                extra = json.loads(row["extra"])
                if "hermes_session_id" in extra:
                    existing.add(extra["hermes_session_id"])
            except (json.JSONDecodeError, KeyError):
                pass
        tk_conn.close()
    except sqlite3.Error:
        pass

    # 查询 Hermes 的 sessions（带 token 数据）
    try:
        sessions = hermes_conn.execute("""
            SELECT
                id, title, billing_provider, model,
                input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens, reasoning_tokens,
                estimated_cost_usd, actual_cost_usd,
                started_at, ended_at
            FROM sessions
            WHERE (input_tokens > 0 OR output_tokens > 0)
            ORDER BY started_at DESC
        """).fetchall()
    except sqlite3.Error as e:
        logger.error("查询 Hermes sessions 失败: %s", e)
        hermes_conn.close()
        return 0

    count = 0
    for s in sessions:
        sid = str(s["id"])
        if sid in existing:
            continue

        provider = s["billing_provider"] or "unknown"
        model = s["model"] or "unknown"
        prompt_tokens = s["input_tokens"] or 0
        completion_tokens = s["output_tokens"] or 0
        total_tokens = prompt_tokens + completion_tokens + (s["cache_read_tokens"] or 0)
        cost_usd = s["actual_cost_usd"] or s["estimated_cost_usd"] or 0

        # 估算 CNY（汇率 ~7.2）
        cost_cny = round(cost_usd * 7.2, 6) if cost_usd else 0

        timestamp = s["started_at"] or s["ended_at"] or time.time()
        if isinstance(timestamp, str):
            try:
                from datetime import datetime
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                timestamp = time.time()

        record = CallRecord(
            timestamp=float(timestamp),
            project="hermes",
            user="me",
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=s["cache_read_tokens"] or 0,
            cost_usd=cost_usd,
            cost_cny=cost_cny,
            latency_ms=0,
            status="success",
            extra={"hermes_session_id": sid, "title": s["title"]},
        )

        try:
            ledger.record(record)
            count += 1
        except Exception as e:
            logger.error("写入 tokenkeeper 失败 (session %s): %s", sid, e)

    hermes_conn.close()
    logger.info("同步完成: %d 条新记录", count)
    return count


def _ensure_tk_installed(db_path: str) -> bool:
    """确保 tokenkeeper 已安装。"""
    from tokenkeeper.core import guard as api
    try:
        if not api.is_installed():
            api.install(db_path=db_path, project="hermes", user="me")
        return True
    except Exception as e:
        logger.error("安装 tokenkeeper 失败: %s", e)
        return False
