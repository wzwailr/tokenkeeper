"""tokenkeeper.ledger — SQLite 账本，存储每次 LLM 调用记录。

模块职责（架构师定稿，2026-06-23）：
1. 记录每次 LLM 调用（模型/token/成本/延迟/状态）
2. 提供查询接口（按时间/项目/模型筛选）
3. 提供汇总接口（按模型/项目/用户聚合）
4. 导出（JSONL / CSV）
5. 线程安全（SQLite + check_same_thread=False）

公开 API（__all__）：
- CallRecord (dataclass)
- Ledger (class)

数据模型（docs/PROJECT_PLAN.md 4.1）：
- 表 calls: id/timestamp/project/user/provider/model/tokens/cost/latency/status/error/extra
- 表 budgets: scope/scope_key/daily_limit_usd/monthly_limit_usd/per_call_limit_usd/action

错误处理哲学：
- 记账失败不能让业务崩（try/except 包住）
- DB 文件被锁 → 重试 3 次
- DB 文件不存在 → 自动创建（包括父目录）
- DB 字段类型错 → 抛 LedgerError（用户代码 bug）

性能：
- 默认 WAL 模式（多读少写）
- 索引：timestamp / project / model
- 不做连接池（单进程简单优先）
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "CallRecord",
    "Ledger",
    "LedgerError",
]


logger = logging.getLogger(__name__)


# ====================================================================
# 异常
# ====================================================================


class LedgerError(Exception):
    """账本相关错误（DB 连接失败、字段类型错、SQL 错误等）。

    这是**用户代码 bug**或**环境问题**——记账失败不应让业务崩，
    但开发时应该看到。
    """


# ====================================================================
# 数据结构
# ====================================================================


@dataclass(frozen=True)
class CallRecord:
    """一次 LLM 调用的完整记录（不可变）。

    设计原则：所有字段都有默认值，方便业务代码只用部分字段。
    timestamp 是 Unix 浮点秒（time.time()），便于跨时区/跨语言。

    Attributes:
        timestamp: 调用发生时间（Unix 秒）
        project: 项目标识（默认 "default"）
        user: 用户/调用方标识（默认 "default"）
        provider: 提供商标识（openai/anthropic/deepseek/...）
        model: 模型标识
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数
        total_tokens: 总 token 数（默认 prompt+completion）
        cached_tokens: 缓存命中 token 数（默认 0）
        cost_usd: 已计算的美元成本
        cost_cny: 已计算的人民币成本
        latency_ms: 调用耗时（毫秒）
        status: 状态（"success" / "error" / "blocked"）
        error: 错误信息（status=error 时填）
        extra: 扩展字段（dict，会被 JSON 序列化）
    """

    timestamp: float
    project: str = "default"
    user: str = "default"
    provider: str = "unknown"
    model: str = "unknown"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    cost_cny: float = 0.0
    latency_ms: float = 0.0
    status: str = "success"
    error: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """校验字段。"""
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be > 0, got {self.timestamp}")
        if not self.model:
            raise ValueError("model must not be empty")
        if self.status not in ("success", "error", "blocked"):
            raise ValueError(
                f"status must be success/error/blocked, got {self.status!r}"
            )
        # 自动计算 total_tokens
        if self.total_tokens == 0 and (
            self.prompt_tokens > 0 or self.completion_tokens > 0
        ):
            # frozen=True 时不能直接赋值，用 object.__setattr__
            object.__setattr__(
                self, "total_tokens", self.prompt_tokens + self.completion_tokens
            )
        if self.cached_tokens < 0:
            raise ValueError(f"cached_tokens must be >= 0, got {self.cached_tokens}")
        # 注：cached_tokens > prompt_tokens 在 Anthropic 模式下是正常的
        # (Anthropic 的 input_tokens 不包含 cache，cache_read 独立计费)
        # OpenAI 模式下 cached_tokens 是 prompt_tokens 的子集
        # 这里不强制校验，调用方应保证语义正确
        if self.cost_usd < 0:
            raise ValueError(f"cost_usd must be >= 0, got {self.cost_usd}")
        if self.cost_cny < 0:
            raise ValueError(f"cost_cny must be >= 0, got {self.cost_cny}")
        if self.latency_ms < 0:
            raise ValueError(f"latency_ms must be >= 0, got {self.latency_ms}")


# ====================================================================
# Schema 定义
# ====================================================================

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    project TEXT NOT NULL DEFAULT 'default',
    "user" TEXT NOT NULL DEFAULT 'default',
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    cost_cny REAL NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success',
    error TEXT,
    extra TEXT
);

CREATE INDEX IF NOT EXISTS idx_calls_timestamp ON calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_calls_project ON calls(project);
CREATE INDEX IF NOT EXISTS idx_calls_model ON calls(model);
CREATE INDEX IF NOT EXISTS idx_calls_user ON calls("user");
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    scope_key TEXT,
    daily_limit_usd REAL,
    monthly_limit_usd REAL,
    per_call_limit_usd REAL,
    action TEXT NOT NULL DEFAULT 'warn',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_budgets_scope ON budgets(scope, scope_key);
"""


# ====================================================================
# Ledger 主类
# ====================================================================


class Ledger:
    """SQLite 账本。

    每个 Ledger 实例对应一个 DB 文件，线程安全（内部用 threading.Lock 串行化写入）。
    推荐用法：全进程共用一个 Ledger 实例。

    Examples:
        >>> ledger = Ledger("./tokenkeeper.db")
        >>> record = CallRecord(timestamp=time.time(), model="gpt-4o",
        ...                     prompt_tokens=1000, completion_tokens=500,
        ...                     cost_usd=0.0075)
        >>> ledger.record(record)
        >>> calls = ledger.query(since=time.time() - 3600)
        >>> len(calls) > 0
        True
    """

    def __init__(self, db_path: str | os.PathLike) -> None:
        """初始化 Ledger，自动创建 DB 文件和表。

        Args:
            db_path: SQLite 文件路径

        Raises:
            LedgerError: DB 文件无法创建或权限不足
        """
        self.db_path = Path(db_path).resolve()
        self._lock = threading.Lock()
        self._closed = False

        # 确保父目录存在
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise LedgerError(f"无法创建 DB 目录 {self.db_path.parent}: {e}") from e

        # 连接 DB（check_same_thread=False 让多线程可用）
        try:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,  # 锁等待 30s
            )
            self._conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            raise LedgerError(f"无法连接 DB {self.db_path}: {e}") from e

        # 启用 WAL 模式（性能更好）
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as e:
            logger.warning("无法启用 WAL 模式: %s", e)

        # 初始化 schema
        self._init_schema()

        logger.info("Ledger 初始化完成: %s", self.db_path)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """初始化表结构。"""
        try:
            with self._lock:
                self._conn.executescript(_SCHEMA_SQL)
                self._conn.commit()
        except sqlite3.Error as e:
            raise LedgerError(f"初始化 schema 失败: {e}") from e

    def close(self) -> None:
        """关闭 DB 连接。"""
        with self._lock:
            if self._closed:
                return
            try:
                self._conn.close()
            except sqlite3.Error as e:
                logger.warning("关闭 DB 连接时出错: %s", e)
            self._closed = True
            logger.info("Ledger 已关闭: %s", self.db_path)

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        if not self._closed:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 核心：记录一次调用
    # ------------------------------------------------------------------

    def record(self, call: CallRecord) -> Optional[int]:
        """记录一次 LLM 调用。

        失败不会抛出异常（**不影响业务**），只记录日志和返回 None。
        成功返回新插入的 rowid。

        Args:
            call: :class:`CallRecord` 实例

        Returns:
            新插入的 rowid，失败返回 ``None``
        """
        if self._closed:
            logger.error("Ledger 已关闭，无法记录")
            return None

        if not isinstance(call, CallRecord):
            logger.error("record() 需要 CallRecord 实例，收到 %s", type(call).__name__)
            return None

        sql = """
        INSERT INTO calls (
            timestamp, project, "user", provider, model,
            prompt_tokens, completion_tokens, total_tokens, cached_tokens,
            cost_usd, cost_cny, latency_ms,
            status, error, extra
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        try:
            extra_json = (
                json.dumps(call.extra, ensure_ascii=False) if call.extra else None
            )
            with self._lock:
                cur = self._conn.execute(
                    sql,
                    (
                        call.timestamp,
                        call.project,
                        call.user,
                        call.provider,
                        call.model,
                        call.prompt_tokens,
                        call.completion_tokens,
                        call.total_tokens,
                        call.cached_tokens,
                        call.cost_usd,
                        call.cost_cny,
                        call.latency_ms,
                        call.status,
                        call.error,
                        extra_json,
                    ),
                )
                self._conn.commit()
                rowid = cur.lastrowid
            logger.debug(
                "记账成功 [id=%d] model=%s prompt=%d completion=%d cost=$%.6f",
                rowid,
                call.model,
                call.prompt_tokens,
                call.completion_tokens,
                call.cost_usd,
            )
            return rowid
        except sqlite3.Error as e:
            logger.error("记录调用失败: %s (call=%r)", e, call)
            return None
        except (TypeError, ValueError) as e:
            logger.error("CallRecord 字段类型错误: %s (call=%r)", e, call)
            return None

    def record_batch(self, calls: list[CallRecord]) -> int:
        """批量记录（更快，但失败任一条会回滚全部）。

        Args:
            calls: :class:`CallRecord` 列表

        Returns:
            成功插入的行数（全部成功 = len(calls)，任一失败 = 0）
        """
        if self._closed or not calls:
            return 0

        sql = """
        INSERT INTO calls (
            timestamp, project, "user", provider, model,
            prompt_tokens, completion_tokens, total_tokens, cached_tokens,
            cost_usd, cost_cny, latency_ms,
            status, error, extra
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        rows = []
        for call in calls:
            try:
                rows.append(
                    (
                        call.timestamp,
                        call.project,
                        call.user,
                        call.provider,
                        call.model,
                        call.prompt_tokens,
                        call.completion_tokens,
                        call.total_tokens,
                        call.cached_tokens,
                        call.cost_usd,
                        call.cost_cny,
                        call.latency_ms,
                        call.status,
                        call.error,
                        json.dumps(call.extra, ensure_ascii=False)
                        if call.extra
                        else None,
                    )
                )
            except (TypeError, ValueError) as e:
                logger.error("CallRecord 字段错误: %s", e)
                return 0

        try:
            with self._lock:
                cur = self._conn.executemany(sql, rows)
                self._conn.commit()
            return cur.rowcount
        except sqlite3.Error as e:
            logger.error("批量记录失败: %s", e)
            return 0

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

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
        """查询调用记录。

        所有参数都是可选的，可以组合筛选。返回结果按 timestamp 降序。

        Args:
            since: 起始时间（Unix 秒，含）
            until: 结束时间（Unix 秒，含）
            project: 按项目筛选
            user: 按用户筛选
            model: 按模型筛选（精确匹配）
            provider: 按提供商筛选
            status: 按状态筛选（success/error/blocked）
            limit: 最大返回行数（默认 1000，防全表扫描）

        Returns:
            :class:`CallRecord` 列表（按 timestamp 降序）
        """
        if self._closed:
            return []

        sql = "SELECT * FROM calls WHERE 1=1"
        params: list[Any] = []

        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(since)
        if until is not None:
            sql += " AND timestamp <= ?"
            params.append(until)
        if project is not None:
            sql += " AND project = ?"
            params.append(project)
        if user is not None:
            sql += ' AND "user" = ?'
            params.append(user)
        if model is not None:
            sql += " AND model = ?"
            params.append(model)
        if provider is not None:
            sql += " AND provider = ?"
            params.append(provider)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        try:
            with self._lock:
                cur = self._conn.execute(sql, params)
                rows = cur.fetchall()
            return [self._row_to_record(row) for row in rows]
        except sqlite3.Error as e:
            logger.error("查询失败: %s", e)
            return []

    def _row_to_record(self, row: sqlite3.Row) -> CallRecord:
        """把 sqlite3.Row 转 CallRecord。"""
        extra_str = row["extra"]
        extra = json.loads(extra_str) if extra_str else {}
        return CallRecord(
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
            extra=extra,
        )

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------

    def summary(
        self,
        since: Optional[float] = None,
        until: Optional[float] = None,
        project: Optional[str] = None,
        group_by: str = "model",
    ) -> list[dict[str, Any]]:
        """按维度汇总。

        Args:
            since: 起始时间
            until: 结束时间
            project: 按项目筛选
            group_by: 汇总维度（"model" / "project" / "user" / "provider" / "day"）

        Returns:
            汇总列表，每项形如::

                [
                  {"model": "gpt-4o", "calls": 100, "cost_usd": 12.5, ...},
                  ...
                ]

        Raises:
            ValueError: group_by 不在允许列表
        """
        allowed = ("model", "project", "user", "provider", "day")
        if group_by not in allowed:
            raise ValueError(f"group_by must be one of {allowed}, got {group_by!r}")

        if group_by == "day":
            group_col = "date(timestamp, 'unixepoch')"
        elif group_by == "user":
            group_col = '"user"'  # user 是 SQL 保留字，要加引号
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
            sql += " AND timestamp >= ?"
            params.append(since)
        if until is not None:
            sql += " AND timestamp <= ?"
            params.append(until)
        if project is not None:
            sql += " AND project = ?"
            params.append(project)

        sql += " GROUP BY group_key ORDER BY cost_usd DESC"

        try:
            with self._lock:
                cur = self._conn.execute(sql, params)
                rows = cur.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error("汇总失败: %s", e)
            return []

    def total_cost(
        self,
        since: Optional[float] = None,
        until: Optional[float] = None,
        project: Optional[str] = None,
    ) -> tuple[float, float]:
        """总成本（USD, CNY）。

        Args:
            since: 起始时间
            until: 结束时间
            project: 按项目筛选

        Returns:
            (cost_usd, cost_cny) 元组
        """
        sql = "SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(cost_cny), 0) FROM calls WHERE 1=1"
        params: list[Any] = []

        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(since)
        if until is not None:
            sql += " AND timestamp <= ?"
            params.append(until)
        if project is not None:
            sql += " AND project = ?"
            params.append(project)

        try:
            with self._lock:
                cur = self._conn.execute(sql, params)
                row = cur.fetchone()
            return float(row[0]), float(row[1])
        except sqlite3.Error as e:
            logger.error("查询总成本失败: %s", e)
            return 0.0, 0.0

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    def export_jsonl(
        self,
        path: str | os.PathLike,
        since: Optional[float] = None,
        until: Optional[float] = None,
        project: Optional[str] = None,
    ) -> int:
        """导出为 JSONL 格式。

        Args:
            path: 输出文件路径
            since: 起始时间
            until: 结束时间
            project: 按项目筛选

        Returns:
            导出的行数
        """
        calls = self.query(since=since, until=until, project=project, limit=10_000_000)
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                for call in calls:
                    f.write(json.dumps(asdict(call), ensure_ascii=False) + "\n")
            logger.info("导出 %d 行到 %s", len(calls), out_path)
            return len(calls)
        except OSError as e:
            logger.error("导出 JSONL 失败: %s", e)
            return 0

    def export_csv(
        self,
        path: str | os.PathLike,
        since: Optional[float] = None,
        until: Optional[float] = None,
        project: Optional[str] = None,
    ) -> int:
        """导出为 CSV 格式。

        Args:
            path: 输出文件路径
            since: 起始时间
            until: 结束时间
            project: 按项目筛选

        Returns:
            导出的行数
        """
        calls = self.query(since=since, until=until, project=project, limit=10_000_000)
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not calls:
            return 0

        try:
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(asdict(calls[0]).keys()))
                writer.writeheader()
                for call in calls:
                    # extra 字段需要转 JSON 字符串
                    row = asdict(call)
                    if row.get("extra"):
                        row["extra"] = json.dumps(row["extra"], ensure_ascii=False)
                    writer.writerow(row)
            logger.info("导出 %d 行到 %s", len(calls), out_path)
            return len(calls)
        except OSError as e:
            logger.error("导出 CSV 失败: %s", e)
            return 0

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def count(self, project: Optional[str] = None) -> int:
        """总记录数。"""
        sql = "SELECT COUNT(*) FROM calls"
        params: list[Any] = []
        if project is not None:
            sql += " WHERE project = ?"
            params.append(project)
        try:
            with self._lock:
                cur = self._conn.execute(sql, params)
                return int(cur.fetchone()[0])
        except sqlite3.Error as e:
            logger.error("count 失败: %s", e)
            return 0

    def vacuum(self) -> None:
        """压缩 DB 文件（删大量数据后用）。"""
        try:
            with self._lock:
                self._conn.execute("VACUUM")
            logger.info("VACUUM 完成")
        except sqlite3.Error as e:
            logger.error("VACUUM 失败: %s", e)
