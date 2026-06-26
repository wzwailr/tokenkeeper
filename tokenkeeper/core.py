"""tokenkeeper.core — 拦截核心与顶级 guard API。

模块职责（架构师定稿，2026-06-23）：
1. 提供顶级 ``guard`` API（``guard.install()`` / ``guard.uninstall()``）
2. 协调 ledger + guard + 各种 integrations
3. 维护"已 patch 的 SDK"状态，防止重复 patch
4. 提供上下文管理器（``guard.temporarily_disabled()``）

公开 API（__all__）：
- guard (顶级单例)
- GuardAPI (类)

设计：
- ``guard`` 是全局单例，第一次 ``from tokenkeeper import guard`` 时创建
- ``guard.install()`` 一次性初始化 ledger + 注册拦截器
- ``guard.uninstall()`` 恢复原始 SDK 方法
- 重复 install() 是幂等的（不会重复 patch）
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .guard import Budget, BudgetExceededError, Guard, GuardDecision
from .ledger import Ledger

__all__ = [
    "guard",
    "GuardAPI",
    "Budget",
    "BudgetExceededError",
    "GuardDecision",
]


logger = logging.getLogger(__name__)


# ====================================================================
# 顶级 guard API
# ====================================================================


class GuardAPI:
    """tokenkeeper 顶级 API（用户用 ``from tokenkeeper import guard``）。

    这是单例（顶层只有一个 guard 实例）。线程安全。

    Examples:
        >>> from tokenkeeper import guard
        >>> guard.install(project="my-app", db_path="./tk.db")
        >>> guard.set_budget(daily_limit_usd=10.0, action="block")
        >>> # 业务代码 0 改动，openai 调用自动记账 + 限额
        >>> guard.uninstall()
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ledger: Optional[Ledger] = None
        self._guard: Optional[Guard] = None
        self._installed: bool = False
        self._project: str = "default"
        self._user: str = "default"
        self._patched_sdks: list[str] = []  # 跟踪已 patch 的 SDK

    # ------------------------------------------------------------------
    # 安装 / 卸载
    # ------------------------------------------------------------------

    def install(
        self,
        db_path: str | Path = "./tokenkeeper.db",
        project: str = "default",
        user: str = "default",
        auto_patch_openai: bool = True,
    ) -> None:
        """安装 tokenkeeper。

        - 创建/打开 ledger
        - 创建 guard
        - （可选）自动 patch OpenAI SDK

        重复调用是幂等的。

        Args:
            db_path: SQLite 文件路径
            project: 项目标识
            user: 用户标识
            auto_patch_openai: 是否自动 patch OpenAI SDK（默认 True）
        """
        with self._lock:
            if self._installed:
                logger.debug("guard.install() 重复调用，已安装，跳过")
                return

            # 1. 创建 ledger
            self._ledger = Ledger(db_path)
            self._project = project
            self._user = user

            # 2. 创建 guard
            self._guard = Guard(self._ledger)

            # 3. （可选）自动 patch OpenAI SDK
            if auto_patch_openai:
                try:
                    self._patch_openai()
                except ImportError:
                    logger.warning(
                        "openai 包未安装，跳过 patch。"
                        "用户调用 openai 时不会被 tokenkeeper 拦截。"
                    )
                except Exception as e:
                    logger.error("patch SDK 失败，但 tokenkeeper 仍可使用: %s", e)

            # 确保即使 patch 失败，tokenkeeper 也算安装成功
            try:
                self._installed = True
                logger.info(
                    "tokenkeeper 已安装: db=%s project=%s user=%s",
                    db_path,
                    project,
                    user,
                )
            except Exception as e:
                logger.error("设置 _installed 失败: %s", e)
                raise
                raise

    def uninstall(self) -> None:
        """卸载 tokenkeeper，恢复原始 SDK。"""
        with self._lock:
            if not self._installed:
                return

            # 恢复 SDK
            for sdk_name in self._patched_sdks:
                try:
                    self._unpatch_sdk(sdk_name)
                except Exception as e:
                    logger.error("unpatch %s 失败: %s", sdk_name, e)
            self._patched_sdks.clear()

            # 关闭 ledger
            if self._ledger is not None:
                self._ledger.close()

            self._ledger = None
            self._guard = None
            self._installed = False
            logger.info("tokenkeeper 已卸载")

    @contextmanager
    def temporarily_disabled(self) -> Iterator[None]:
        """上下文管理器：临时关闭拦截（用于性能关键路径）。

        Examples:
            >>> with guard.temporarily_disabled():
            ...     # 这里的 openai 调用不会被记账
            ...     client.chat.completions.create(...)
        """
        was_installed = self._installed
        if was_installed:
            self.uninstall()
        try:
            yield
        finally:
            if was_installed:
                self.install(
                    db_path=str(self._ledger.db_path)
                    if self._ledger
                    else "./tokenkeeper.db",
                    project=self._project,
                    user=self._user,
                )

    # ------------------------------------------------------------------
    # 预算管理（代理到内部 _guard）
    # ------------------------------------------------------------------

    def set_budget(
        self,
        daily_limit_usd: Optional[float] = None,
        monthly_limit_usd: Optional[float] = None,
        per_call_limit_usd: Optional[float] = None,
        action: str = "block",
        scope: str = "global",
        scope_key: Optional[str] = None,
    ) -> None:
        """设置预算（快捷方法）。

        Args:
            daily_limit_usd: 日预算
            monthly_limit_usd: 月预算
            per_call_limit_usd: 单次预算
            action: 超限动作（"block" / "warn"）
            scope: 范围（"global" / "project" / "user"）
            scope_key: scope 为 project/user 时必填
        """
        if not self._installed:
            raise RuntimeError("请先调用 guard.install()")
        budget = Budget(
            scope=scope,
            scope_key=scope_key,
            daily_limit_usd=daily_limit_usd,
            monthly_limit_usd=monthly_limit_usd,
            per_call_limit_usd=per_call_limit_usd,
            action=action,
        )
        if self._guard is not None:
            self._guard.set_budget(budget)

    def clear_budgets(self) -> None:
        """清空所有预算。"""
        if not self._installed:
            return
        if self._guard is not None:
            self._guard.clear_budgets()

    # ------------------------------------------------------------------
    # 直接记账（用户手动调用）
    # ------------------------------------------------------------------

    def record(
        self,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        cost_cny: float = 0.0,
        latency_ms: float = 0.0,
        status: str = "success",
        error: Optional[str] = None,
        provider: str = "unknown",
    ) -> Optional[int]:
        """手动记录一次调用（用于非 OpenAI SDK 的场景）。

        Returns:
            新插入的 rowid，失败 None
        """
        if not self._installed or self._ledger is None:
            logger.error("guard 未安装，无法记录")
            return None

        from .ledger import CallRecord
        import time

        record = CallRecord(
            timestamp=time.time(),
            project=self._project,
            user=self._user,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            cost_cny=cost_cny,
            latency_ms=latency_ms,
            status=status,
            error=error,
        )
        return self._ledger.record(record)

    # ------------------------------------------------------------------
    # 查询（代理到 ledger）
    # ------------------------------------------------------------------

    def query(self, **kwargs: Any) -> list[Any]:
        """查询调用记录（代理到 ledger）。"""
        if not self._installed or self._ledger is None:
            return []
        return self._ledger.query(**kwargs)

    def summary(self, **kwargs: Any) -> list[dict[str, Any]]:
        """汇总（代理到 ledger）。"""
        if not self._installed or self._ledger is None:
            return []
        return self._ledger.summary(**kwargs)

    def total_cost(self, **kwargs: Any) -> tuple[float, float]:
        """总成本（代理到 ledger）。"""
        if not self._installed or self._ledger is None:
            return 0.0, 0.0
        return self._ledger.total_cost(**kwargs)

    # ------------------------------------------------------------------
    # SDK Patch 管理
    # ------------------------------------------------------------------

    def _patch_openai(self) -> bool:
        """patch OpenAI 和 Anthropic SDK（延迟 import）。

        Returns:
            bool: 是否成功 patch 至少一个 SDK
        """
        success = False

        try:
            # OpenAI 兼容协议
            try:
                from .integrations.openai_compat import install as install_openai

                install_openai(self)
                self._patched_sdks.append("openai")
                logger.info("OpenAI SDK 已 patch")
                success = True
            except ImportError as e:
                logger.warning("无法 import openai_compat: %s", e)
            except Exception as e:
                logger.error("patch OpenAI 失败: %s", e)

            # Anthropic 原生 SDK
            try:
                from .integrations.anthropic import install as install_anthropic

                install_anthropic(self)
                self._patched_sdks.append("anthropic")
                logger.info("Anthropic SDK 已 patch")
                success = True
            except ImportError as e:
                logger.warning("无法 import anthropic: %s", e)
            except Exception as e:
                logger.error("patch Anthropic 失败: %s", e)
                # 不影响 _installed 状态，只是 Anthropic 不记账
        except Exception as e:
            logger.error("patch SDK 过程中发生未预期错误: %s", e)

        return success

    def _unpatch_sdk(self, sdk_name: str) -> None:
        """unpatch SDK。"""
        if sdk_name == "openai":
            try:
                from .integrations.openai_compat import uninstall as uninstall_openai

                uninstall_openai()
                logger.info("OpenAI SDK 已 unpatch")
            except ImportError:
                pass
        elif sdk_name == "anthropic":
            try:
                from .integrations.anthropic import uninstall as uninstall_anthropic

                uninstall_anthropic()
                logger.info("Anthropic SDK 已 unpatch")
            except ImportError:
                pass

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def is_installed(self) -> bool:
        """是否已安装。"""
        return self._installed

    def ledger(self) -> Optional[Ledger]:
        """获取内部 ledger 实例（高级用户用）。"""
        return self._ledger

    def guard_instance(self) -> Optional[Guard]:
        """获取内部 guard 实例（高级用户用）。"""
        return self._guard


# 全局单例
guard = GuardAPI()
