"""tokenkeeper PostgreSQL 后端。

用法::

    ledger = Ledger("postgresql://user:pass@localhost:5432/tokenkeeper")
    ledger.record(...)

与 SQLite 后端接口完全兼容。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

from tokenkeeper.ledger import CallRecord

logger = logging.getLogger(__name__)

__all__ = ["PostgresLedger"]


class PostgresLedger:
    """PostgreSQL 账本后端 — 与 Ledger 接口兼容。

    Args:
        dsn: PostgreSQL DSN，格式:
            postgresql://user:pass@host:port/dbname
    """

    def __init__(self, dsn: str) -> None:
        if not HAS_PSYCOPG2:
            raise ImportError(
                "psycopg2 未安装。请运行: pip install tokenkeeper-ai[postgres] 或 pip install psycopg2-binary"
            )
        self.dsn = dsn
        self._lock = threading.Lock()
        self._closed = False
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False
        self._init_schema()

    def _init_schema(self) -> None:
        """创建表（如不存在）。"""
        sql = """
        CREATE TABLE IF NOT EXISTS calls (
            id SERIAL PRIMARY KEY,
            timestamp DOUBLE PRECISION NOT NULL,
            project VARCHAR(255) NOT NULL DEFAULT 'default',
            "user" VARCHAR(255) NOT NULL DEFAULT 'default',
            provider VARCHAR(100) NOT NULL DEFAULT 'unknown',
            model VARCHAR(255) NOT NULL DEFAULT 'unknown',
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            cached_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
            cost_cny DOUBLE PRECISION NOT NULL DEFAULT 0,
            latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'success',
            error TEXT,
            extra TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_calls_project ON calls(project);
        CREATE INDEX IF NOT EXISTS idx_calls_timestamp ON calls(timestamp);
        CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
        """
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql)
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            logger.error("创建 PostgreSQL 表失败: %s", e)
            raise

    def close(self) -> None:
        """关闭连接。"""
        if not self._closed:
            self._closed = True
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "PostgresLedger":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 数据操作（与 Ledger 相同接口）
    # ------------------------------------------------------------------

    def record(self, call: CallRecord) -> Optional[int]:
        """记录一次 LLM 调用。"""
        if self._closed:
            return None

        sql = """
        INSERT INTO calls (
            timestamp, project, "user", provider, model,
            prompt_tokens, completion_tokens, total_tokens, cached_tokens,
            cost_usd, cost_cny, latency_ms, status, error, extra
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """
        try:
            with self._lock:
                with self._conn.cursor() as cur:
                    cur.execute(sql, (
                        call.timestamp, call.project, call.user,
                        call.provider, call.model,
                        call.prompt_tokens, call.completion_tokens,
                        call.total_tokens, call.cached_tokens,
                        call.cost_usd, call.cost_cny, call.latency_ms,
                        call.status, call.error,
                        json.dumps(call.extra) if call.extra else None,
                    ))
                    row = cur.fetchone()
                self._conn.commit()
            return row[0] if row else None
        except Exception as e:
            self._conn.rollback()
            logger.error("记录失败: %s", e)
            return None

    def record_batch(self, calls: list[CallRecord]) -> int:
        """批量记录。"""
        if self._closed or not calls:
            return 0
        count = 0
        try:
            with self._lock:
                with self._conn.cursor() as cur:
                    for call in calls:
                        cur.execute("""
                        INSERT INTO calls (
                            timestamp, project, "user", provider, model,
                            prompt_tokens, completion_tokens, total_tokens, cached_tokens,
                            cost_usd, cost_cny, latency_ms, status, error, extra
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            call.timestamp, call.project, call.user,
                            call.provider, call.model,
                            call.prompt_tokens, call.completion_tokens,
                            call.total_tokens, call.cached_tokens,
                            call.cost_usd, call.cost_cny, call.latency_ms,
                            call.status, call.error,
                            json.dumps(call.extra) if call.extra else None,
                        ))
                        count += 1
                self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            logger.error("批量记录失败: %s", e)
            return 0
        return count

    def query(
        self,
        since: Optional[float] = None,
        until: Optional[float] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000,
    ) -> list[CallRecord]:
        """查询调用记录。"""
        sql = "SELECT * FROM calls WHERE 1=1"
        params: list[Any] = []

        if since is not None:
            sql += " AND timestamp >= %s"
            params.append(since)
        if until is not None:
            sql += " AND timestamp <= %s"
            params.append(until)
        if project is not None:
            sql += " AND project = %s"
            params.append(project)
        if user is not None:
            sql += ' AND "user" = %s'
            params.append(user)
        if model is not None:
            sql += " AND model = %s"
            params.append(model)
        if provider is not None:
            sql += " AND provider = %s"
            params.append(provider)
        if status is not None:
            sql += " AND status = %s"
            params.append(status)

        sql += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)

        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            return [
                CallRecord(
                    timestamp=row["timestamp"],
                    project=row["project"],
                    user=row["user"],
                    provider=row["provider"],
                    model=row["model"],
                    prompt_tokens=row["prompt_tokens"],
                    completion_tokens=row["completion_tokens"],
                    total_tokens=row["total_tokens"],
                    cached_tokens=row["cached_tokens"],
                    cost_usd=row["cost_usd"],
                    cost_cny=row["cost_cny"],
                    latency_ms=row["latency_ms"],
                    status=row["status"],
                    error=row["error"],
                    extra=json.loads(row["extra"]) if row["extra"] else None,
                )
                for row in rows
            ]
        except Exception as e:
            logger.error("查询失败: %s", e)
            return []

    def summary(
        self,
        since: Optional[float] = None,
        until: Optional[float] = None,
        project: Optional[str] = None,
        group_by: str = "model",
    ) -> list[dict[str, Any]]:
        """按维度汇总。"""
        allowed = ("model", "project", "user", "provider", "day")
        if group_by not in allowed:
            raise ValueError(f"group_by must be one of {allowed}")

        if group_by == "day":
            group_col = "date(to_timestamp(timestamp))"
        elif group_by == "user":
            group_col = '"user"'
        else:
            group_col = group_by

        sql = f"""
        SELECT
            {group_col} AS group_key,
            COUNT(*) AS calls,
            SUM(prompt_tokens) AS prompt_tokens,
            SUM(completion_tokens) AS completion_tokens,
            SUM(total_tokens) AS total_tokens,
            SUM(cached_tokens) AS cached_tokens,
            SUM(cost_usd) AS cost_usd,
            SUM(cost_cny) AS cost_cny,
            AVG(latency_ms) AS avg_latency_ms,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
            SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked
        FROM calls
        WHERE 1=1
        """
        params: list[Any] = []

        if since is not None:
            sql += " AND timestamp >= %s"
            params.append(since)
        if until is not None:
            sql += " AND timestamp <= %s"
            params.append(until)
        if project is not None:
            sql += " AND project = %s"
            params.append(project)

        sql += " GROUP BY group_key ORDER BY cost_usd DESC"

        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("汇总失败: %s", e)
            return []

    def total_cost(
        self,
        since: Optional[float] = None,
        until: Optional[float] = None,
        project: Optional[str] = None,
    ) -> tuple[float, float]:
        """总成本（USD, CNY）。"""
        sql = "SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(cost_cny), 0) FROM calls WHERE 1=1"
        params: list[Any] = []

        if since is not None:
            sql += " AND timestamp >= %s"
            params.append(since)
        if until is not None:
            sql += " AND timestamp <= %s"
            params.append(until)
        if project is not None:
            sql += " AND project = %s"
            params.append(project)

        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            return float(row[0]), float(row[1])
        except Exception as e:
            logger.error("查询总成本失败: %s", e)
            return 0.0, 0.0

    def count(self, project: Optional[str] = None) -> int:
        """记录总数。"""
        sql = "SELECT COUNT(*) FROM calls"
        params: list[Any] = []
        if project:
            sql += " WHERE project = %s"
            params.append(project)
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0
