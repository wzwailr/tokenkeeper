"""tokenkeeper 基础使用示例。

这个示例展示 tokenkeeper 的完整工作流：
1. 安装 guard
2. 配置预算
3. 记录 LLM 调用（手动方式）
4. 查询账本
5. 卸载 guard

运行方式::

    python examples/01_basic_usage.py

注意：如果你有 openai 包并配置了 API key，可以解开
"自动拦截模式"那段的注释，体验零侵入接入。
"""

from __future__ import annotations

import os
import sys
import time

# 让脚本能 import tokenkeeper 包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tokenkeeper import guard  # noqa: E402


def main() -> None:
    """基础使用示例主函数。"""
    print("=" * 60)
    print("🪶 tokenkeeper 基础使用示例")
    print("=" * 60)

    # --------------------------------------------------------------
    # 1. 安装 guard
    # --------------------------------------------------------------
    print("\n[1] 安装 guard...")
    db_path = os.path.join(os.path.dirname(__file__), "demo.db")
    # 如果上次有遗留文件，删掉以便演示
    if os.path.exists(db_path):
        os.remove(db_path)

    guard.install(
        db_path=db_path,
        project="demo-app",
        user="alice",
    )
    print(f"   ✓ 已安装 (db={db_path})")

    # --------------------------------------------------------------
    # 2. 配置预算
    # --------------------------------------------------------------
    print("\n[2] 配置预算...")
    guard.set_budget(
        daily_limit_usd=10.0,
        per_call_limit_usd=1.0,
        action="warn",  # 超限只警告，不阻断（演示用）
    )
    print("   ✓ 日预算 $10，单次预算 $1，超限 warn")

    # --------------------------------------------------------------
    # 3. 记录 LLM 调用
    # --------------------------------------------------------------
    print("\n[3] 模拟 3 次 LLM 调用...")

    samples = [
        ("gpt-4o", 1000, 500, 1200),
        ("claude-sonnet-4", 2000, 800, 1500),
        ("deepseek-chat", 5000, 2000, 900),
    ]

    for model, prompt_t, completion_t, latency in samples:
        # 模拟计算成本
        from tokenkeeper.pricing import calculate_cost
        cost = calculate_cost(model, prompt_t, completion_t)

        # 记录
        guard.record(
            model=model,
            prompt_tokens=prompt_t,
            completion_tokens=completion_t,
            cost_usd=cost.cost_usd,
            cost_cny=cost.cost_cny,
            latency_ms=latency,
        )
        print(f"   ✓ {model:20s}  cost=${cost.cost_usd:.4f}  ¥{cost.cost_cny:.4f}")

    # --------------------------------------------------------------
    # 4. 查询账本
    # --------------------------------------------------------------
    print("\n[4] 查询账本...")
    calls = guard.query()
    print(f"   共 {len(calls)} 条记录:")
    for c in calls:
        print(f"     - {c.model:20s}  prompt={c.prompt_tokens:>5d}  "
              f"completion={c.completion_tokens:>4d}  cost=${c.cost_usd:.4f}")

    # --------------------------------------------------------------
    # 5. 汇总
    # --------------------------------------------------------------
    print("\n[5] 按模型汇总...")
    by_model = guard.summary(group_by="model")
    for row in by_model:
        print(f"     {row['group_key']:20s}  "
              f"calls={row['calls']:>3d}  "
              f"total_tokens={row['total_tokens']:>7d}  "
              f"cost=${row['cost_usd']:.4f}")

    # --------------------------------------------------------------
    # 6. 总成本
    # --------------------------------------------------------------
    print("\n[6] 总成本...")
    total_usd, total_cny = guard.total_cost()
    print(f"     ${total_usd:.4f} / ¥{total_cny:.4f}")

    # --------------------------------------------------------------
    # 7. 模拟预算检查
    # --------------------------------------------------------------
    print("\n[7] 预算检查（模拟下一次调用）...")
    estimated = 0.05  # 预估本次调用 $0.05
    decision = guard.guard_instance().check(estimated_cost=estimated, project="demo-app")
    print(f"     预估成本: ${estimated:.4f}")
    print(f"     决策: {decision.value}")

    # --------------------------------------------------------------
    # 8. 卸载 guard
    # --------------------------------------------------------------
    print("\n[8] 卸载 guard...")
    guard.uninstall()
    print(f"   ✓ 已卸载 (db 仍在 {db_path})")

    print("\n" + "=" * 60)
    print("[OK] 基础示例完成")
    print("=" * 60)
    print(f"\n💡 你可以查看 SQLite 数据库:")
    print(f"   sqlite3 {db_path} 'SELECT * FROM calls;'")


if __name__ == "__main__":
    main()