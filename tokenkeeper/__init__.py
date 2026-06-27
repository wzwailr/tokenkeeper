"""tokenkeeper — AI API 成本监控与限流守护者。

Quickstart（5 行接入）::

    from tokenkeeper import guard

    guard.install(project="my-app", user="alice")

    # 你原来的代码一行不改——所有 openai 调用自动记账 + 限额保护

启动看板::

    $ tokenkeeper dashboard
    # → http://localhost:8501

直接查询账本::

    from tokenkeeper import ledger

    calls = ledger.query(since=time.time() - 86400)  # 最近 24 小时
    total_usd, total_cny = ledger.total_cost(since=time.time() - 86400)

详细文档见各子模块：
- :mod:`tokenkeeper.pricing` — 模型价格表与成本计算
- :mod:`tokenkeeper.ledger` — SQLite 账本
- :mod:`tokenkeeper.guard` — 限额熔断
- :mod:`tokenkeeper.core` — 拦截核心
- :mod:`tokenkeeper.integrations.openai_compat` — OpenAI 兼容协议

设计原则（docs/PROJECT_PLAN.md）：
- 零侵入接入（monkey-patch）
- 数据自产（dogfooding）
- 本地优先（SQLite + 本地文件）
- 国内友好（覆盖国产模型）
- MIT 开源

异常层级：
- :class:`tokenkeeper.ledger.LedgerError` — 账本相关错误
- :class:`tokenkeeper.pricing.PricingConfigError` — 价格配置错误
- :class:`tokenkeeper.guard.BudgetExceededError` — 预算超限
"""

from __future__ import annotations

# 版本号遵循语义化版本（semver.org）
from ._version import __version__  # noqa: E402

__author__ = "tokenkeeper contributors"

__all__ = [
    "__version__",
    # 高级 API（用户直接用）
    "guard",
    "ledger",
    "dashboard",
    # 核心数据类（用户可能用）
    "CallRecord",
    "ModelPricing",
    "CostBreakdown",
    # 异常
    "LedgerError",
    "PricingConfigError",
    "BudgetExceededError",
]


# ====================================================================
# 延迟加载（避免循环引用 + 加快 import 速度）
# ====================================================================

# 价格表（无依赖，第一个加载）
from . import pricing  # noqa: E402
from .pricing import (  # noqa: E402,F401
    ModelPricing,
    CostBreakdown,
    PricingConfigError,
    calculate_cost,
    get_pricing,
    list_models,
    register_custom_pricing,
    USD_TO_CNY,
    PRICING_LAST_UPDATED,
)


# 账本（依赖 sqlite3）
from . import ledger  # noqa: E402
from .ledger import (  # noqa: E402,F401
    CallRecord,
    Ledger,
    LedgerError,
)


# 顶级 guard 单例 — 先导入模块（用别名），再覆盖 guard 名称
from . import guard as _guard_mod  # noqa: E402
from .core import guard  # noqa: E402

# guard 模块自身定义 Budget / Guard / GuardDecision / BudgetExceededError
from .guard import (  # noqa: E402,F401
    Budget,
    Guard,
    GuardDecision,
    BudgetExceededError,
    BUDGET_CACHE_TTL_SECONDS,
)


# 拦截核心（依赖 guard）
# 注意：core 暴露顶级 API（guard.install 实际指向 core.install）
from . import core  # noqa: E402,F401


# 集成（可选，依赖 core）
# 注意：导入这个会自动 patch OpenAI SDK
# 所以默认不导入，用户需要时显式 from tokenkeeper.integrations import openai_compat


# 看板（可选，依赖 streamlit）
# 注意：依赖 streamlit，未安装时会报错
# 用户运行 `tokenkeeper dashboard` 时才会触发


__all__ = sorted(
    set(__all__ + pricing.__all__ + ledger.__all__ + _guard_mod.__all__ + core.__all__)
)


# 模块信息（方便调试）
def _info() -> dict:
    """返回 tokenkeeper 运行时信息（用于调试和健康检查）。"""
    return {
        "version": __version__,
        "pricing_models": len(pricing.list_models()),
        "pricing_last_updated": pricing.PRICING_LAST_UPDATED,
        "pricing_overrides": len(pricing._CUSTOM_PRICING),
        "exchange_rate_usd_cny": pricing.get_exchange_rate(),
        "modules_loaded": ["pricing", "ledger", "guard", "core"],
    }


# 启动横幅（导入时打印）
def _banner() -> str:
    """生成 tokenkeeper 启动横幅（ASCII art）。"""
    return f"""
╭─────────────────────────────────────────╮
│  🪶 tokenkeeper v{__version__:<10s}              │
│  AI API 成本监控与限流守护者                │
│  {len(pricing.list_models())} 个内置模型 | 价格更新 {pricing.PRICING_LAST_UPDATED} │
╰─────────────────────────────────────────╯
"""


if __name__ == "__main__":
    # 模块自检
    import json

    print(_banner())
    print("运行时信息:")
    print(json.dumps(_info(), ensure_ascii=False, indent=2))
