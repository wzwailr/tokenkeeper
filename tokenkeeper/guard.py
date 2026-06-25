"""tokenkeeper.guard — 限额熔断器。

模块职责（架构师定稿，2026-06-23）：
1. 配置预算（日 / 月 / 单次）
2. 检查预算是否超限
3. 决定 ALLOW / WARN / BLOCK
4. 与 :mod:`tokenkeeper.ledger` 集成查实际花费

公开 API（__all__）：
- BudgetExceededError
- Guard (class)

设计原则：
- 预算检查应该是**常数时间**（不每次查 DB），用内存缓存
- 缓存定期从 DB 刷新（默认 5 秒）
- action=block 时**真正抛异常**（让用户代码决定怎么处理）
- action=warn 时**只记日志**（不阻断业务）

性能：
- 单次 check() 调用 < 1ms（不需要每次查 DB）
- 缓存失效后查一次 DB（约 1-10ms）
- 线程安全（threading.Lock）
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .ledger import Ledger

__all__ = [
    "BudgetExceededError",
    "GuardDecision",
    "Guard",
    "BUDGET_CACHE_TTL_SECONDS",
]


logger = logging.getLogger(__name__)


# ====================================================================
# 常量
# ====================================================================

#: 缓存过期时间（秒）——预算检查的 DB 查询结果缓存多久
BUDGET_CACHE_TTL_SECONDS: float = 5.0


# ====================================================================
# 异常与枚举
# ====================================================================


class BudgetExceededError(Exception):
    """预算超限异常。

    当 ``action="block"`` 且预算超限时抛出。用户代码可以捕获此异常
    做降级处理（如切换到更便宜的模型、暂停调用、告警等）。

    Attributes:
        scope: 超限的范围（"daily" / "monthly" / "per_call"）
        current_spend: 当前已花费（USD）
        limit: 预算上限（USD）
        project: 项目标识
    """

    def __init__(
        self,
        scope: str,
        current_spend: float,
        limit: float,
        project: str = "default",
    ) -> None:
        self.scope = scope
        self.current_spend = current_spend
        self.limit = limit
        self.project = project
        super().__init__(
            f"预算超限 [{scope}] project={project}: "
            f"已花费 ${current_spend:.4f} / 上限 ${limit:.4f}"
        )


class GuardDecision(Enum):
    """Guard 检查决策。"""

    ALLOW = "allow"          # 允许通过
    WARN = "warn"            # 允许通过，但记 warning
    BLOCK = "block"          # 拒绝


# ====================================================================
# 预算配置
# ====================================================================


@dataclass(frozen=True)
class Budget:
    """单条预算配置（不可变）。

    Attributes:
        scope: 范围（"global" / "project" / "user"）
        scope_key: 项目或用户标识（global 时为 None）
        daily_limit_usd: 日预算上限（None = 不限制）
        monthly_limit_usd: 月预算上限（None = 不限制）
        per_call_limit_usd: 单次预算上限（None = 不限制）
        action: 超限动作（"warn" / "block"）
    """

    scope: str
    scope_key: Optional[str]
    daily_limit_usd: Optional[float] = None
    monthly_limit_usd: Optional[float] = None
    per_call_limit_usd: Optional[float] = None
    action: str = "warn"

    def __post_init__(self) -> None:
        """校验配置合法性。"""
        if self.scope not in ("global", "project", "user"):
            raise ValueError(f"scope must be global/project/user, got {self.scope!r}")
        if self.scope != "global" and not self.scope_key:
            raise ValueError(f"scope_key required when scope={self.scope!r}")
        if self.action not in ("warn", "block"):
            raise ValueError(f"action must be warn/block, got {self.action!r}")

        # 价格字段非负
        for field_name in ("daily_limit_usd", "monthly_limit_usd", "per_call_limit_usd"):
            val = getattr(self, field_name)
            if val is not None and val < 0:
                raise ValueError(f"{field_name} must be >= 0, got {val}")


# ====================================================================
# Guard 主类
# ====================================================================


class Guard:
    """限额熔断器。

    每个 Guard 实例对应一组预算配置，复用一个 Ledger 实例。
    线程安全（内部 Lock）。

    Examples:
        >>> from tokenkeeper import Ledger
        >>> ledger = Ledger("./tokenkeeper.db")
        >>> guard = Guard(ledger)
        >>> guard.set_budget(Budget(scope="global", daily_limit_usd=10.0, action="block"))
        >>> decision = guard.check(estimated_cost=0.05)
        >>> decision == GuardDecision.ALLOW
        True
    """

    def __init__(
        self,
        ledger: Ledger,
        cache_ttl: float = BUDGET_CACHE_TTL_SECONDS,
    ) -> None:
        """初始化 Guard。

        Args:
            ledger: 已初始化的 :class:`Ledger` 实例
            cache_ttl: 预算缓存过期时间（秒），默认 5 秒
        """
        self.ledger = ledger
        self.cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._budgets: list[Budget] = []

        # 缓存：scope+key -> (timestamp, daily_spend, monthly_spend)
        self._cache: dict[tuple[str, Optional[str]], tuple[float, float, float]] = {}

        logger.info("Guard 初始化完成（cache_ttl=%.1fs）", cache_ttl)

    # ------------------------------------------------------------------
    # 预算管理
    # ------------------------------------------------------------------

    def set_budget(self, budget: Budget) -> None:
        """添加一条预算配置（追加到列表，不去重）。

        多条预算可以共存（如 global + project）。检查时所有预算都生效。

        Args:
            budget: :class:`Budget` 实例
        """
        with self._lock:
            self._budgets.append(budget)
            # 清缓存
            self._cache.clear()
        logger.info(
            "添加预算: scope=%s key=%s daily=%s monthly=%s per_call=%s action=%s",
            budget.scope, budget.scope_key,
            budget.daily_limit_usd, budget.monthly_limit_usd,
            budget.per_call_limit_usd, budget.action,
        )

    def clear_budgets(self) -> None:
        """清空所有预算配置。"""
        with self._lock:
            self._budgets.clear()
            self._cache.clear()

    def get_budgets(self) -> list[Budget]:
        """获取所有预算（返回副本）。"""
        with self._lock:
            return list(self._budgets)

    # ------------------------------------------------------------------
    # 预算检查
    # ------------------------------------------------------------------

    def check(
        self,
        estimated_cost: float,
        project: str = "default",
        user: str = "default",
    ) -> GuardDecision:
        """检查预算，决定 ALLOW / WARN / BLOCK。

        流程：
        1. 遍历所有相关预算
        2. 对每个预算，检查 daily/monthly/per_call 是否超限
        3. 返回最严的决策（BLOCK > WARN > ALLOW）

        Args:
            estimated_cost: 本次调用的预估成本（USD）
            project: 项目标识
            user: 用户标识

        Returns:
            :class:`GuardDecision` 枚举值

        Raises:
            BudgetExceededError: 当任一 action=block 的预算超限时
        """
        if estimated_cost < 0:
            raise ValueError(f"estimated_cost must be >= 0, got {estimated_cost}")

        with self._lock:
            budgets = list(self._budgets)

        if not budgets:
            # 没设预算 = 不限制
            return GuardDecision.ALLOW

        worst = GuardDecision.ALLOW
        violations: list[tuple[Budget, str, float, float]] = []

        for budget in budgets:
            # 只检查匹配的 scope
            if budget.scope == "global":
                scope_match = True
            elif budget.scope == "project" and budget.scope_key == project:
                scope_match = True
            elif budget.scope == "user" and budget.scope_key == user:
                scope_match = True
            else:
                scope_match = False
            if not scope_match:
                continue

            # 单次预算
            if budget.per_call_limit_usd is not None and estimated_cost > budget.per_call_limit_usd:
                violations.append((
                    budget, "per_call", estimated_cost, budget.per_call_limit_usd
                ))

            # 日 / 月预算
            daily_spend, monthly_spend = self._get_spend_cached(project)

            if budget.daily_limit_usd is not None and daily_spend >= budget.daily_limit_usd:
                violations.append((
                    budget, "daily", daily_spend, budget.daily_limit_usd
                ))
            elif (
                budget.daily_limit_usd is not None
                and daily_spend + estimated_cost > budget.daily_limit_usd
            ):
                # 预估会超，但还没超——warning
                violations.append((
                    budget, "daily_after_estimate",
                    daily_spend + estimated_cost, budget.daily_limit_usd,
                ))

            if budget.monthly_limit_usd is not None and monthly_spend >= budget.monthly_limit_usd:
                violations.append((
                    budget, "monthly", monthly_spend, budget.monthly_limit_usd
                ))

        # 聚合决策
        for budget, scope, current, limit in violations:
            over = current >= limit
            if budget.action == "block" and over:
                worst = GuardDecision.BLOCK
                # 立即抛异常
                logger.error(
                    "预算超限 block 触发: scope=%s project=%s 当前=$%.4f 上限=$%.4f",
                    scope, project, current, limit,
                )
                raise BudgetExceededError(
                    scope=scope,
                    current_spend=current,
                    limit=limit,
                    project=project,
                )
            elif over:
                # action=warn 但超了 → WARN
                if worst == GuardDecision.ALLOW:
                    worst = GuardDecision.WARN
                logger.warning(
                    "预算超限 warn: scope=%s project=%s 当前=$%.4f 上限=$%.4f",
                    scope, project, current, limit,
                )

        return worst

    # ------------------------------------------------------------------
    # 缓存层
    # ------------------------------------------------------------------

    def _get_spend_cached(self, project: str) -> tuple[float, float]:
        """获取日 / 月已花费（带缓存）。

        Returns:
            (daily_spend, monthly_spend) 单位 USD
        """
        key = (project, None)  # 暂不分 user，未来可加
        now = time.time()

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                ts, daily, monthly = cached
                if now - ts < self.cache_ttl:
                    return daily, monthly

        # 缓存失效或不存在，查 DB
        daily, monthly = self._compute_spend(project)

        with self._lock:
            self._cache[key] = (now, daily, monthly)

        return daily, monthly

    def _compute_spend(self, project: str) -> tuple[float, float]:
        """从 ledger 计算日 / 月已花费。"""
        now = time.time()
        # 当天 00:00
        # 用本地时区（业务上更符合直觉）
        import datetime
        today_start = datetime.datetime.combine(
            datetime.date.today(), datetime.time.min
        ).timestamp()
        # 当月 1 号 00:00
        month_start = datetime.datetime.combine(
            datetime.date.today().replace(day=1), datetime.time.min
        ).timestamp()

        try:
            daily, _ = self.ledger.total_cost(since=today_start, project=project)
            monthly, _ = self.ledger.total_cost(since=month_start, project=project)
            return daily, monthly
        except (sqlite3.Error, OSError) as e:
            logger.error("查询花费失败: %s", e)
            return 0.0, 0.0

    def invalidate_cache(self) -> None:
        """手动清缓存（外部修改 ledger 后调用）。"""
        with self._lock:
            self._cache.clear()


# ====================================================================
# 模块自检脚本（scripts/self_check_guard.py 引用）
# ====================================================================


def _self_check() -> None:  # pragma: no cover
    """模块自检（已迁移到 scripts/self_check_guard.py）。"""
    raise NotImplementedError(
        "自检逻辑已迁移到 scripts/self_check_guard.py"
    )