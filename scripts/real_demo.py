"""录 tokenkeeper × minimax 真实演示视频。

流程：
1. 启动 streamlit 看板（已跑）
2. 重置 demo.db
3. 用 minimax 真 API 跑 5 次调用 → tokenkeeper 自动记账
4. 刷新看板 → 看到数据
5. 演示限额熔断
6. 录交互（playwright）
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 设置 DB
demo_db = str(ROOT / "examples" / "real_demo.db")
os.environ["TOKENKEEPER_DB"] = demo_db

import requests
from tokenkeeper import guard
from tokenkeeper.ledger import Ledger
from tokenkeeper.pricing import calculate_cost


# minimax API key 从环境变量读取（不在文件中硬编码）
API_KEY = os.environ.get("MINIMAX_API_KEY", "")
if not API_KEY:
    print("❌ 请先设置环境变量 MINIMAX_API_KEY")
    print("   export MINIMAX_API_KEY=*** 你的 key")
    sys.exit(1)
BASE_URL = "https://api.minimaxi.com/v1"


def call_minimax(prompt: str, model: str = "MiniMax-M3") -> dict:
    """真实调 minimax API。"""
    r = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    return r.json()


def setup():
    """重置 DB 并安装 guard。"""
    if os.path.exists(demo_db):
        os.remove(demo_db)
    guard.install(db_path=demo_db, project="demo-video", user="presenter")
    print(f"✅ tokenkeeper 已启动: {demo_db}")


def teardown():
    """卸载。"""
    guard.uninstall()
    print("✅ 已卸载")


def phase1_real_calls():
    """阶段 1：真实 minimax 调用（4 个不同模型）。"""
    print("\n" + "=" * 60)
    print("📞 阶段 1：真实 minimax API 调用")
    print("=" * 60)

    test_cases = [
        ("MiniMax-M3", "用一句话介绍 Python 编程语言"),
        ("MiniMax-M3", "9*9 等于几？"),
        ("MiniMax-M3", "列出 3 种水果"),
    ]

    for model, prompt in test_cases:
        t0 = time.time()
        try:
            resp = call_minimax(prompt, model)
            elapsed = (time.time() - t0) * 1000

            usage = resp["usage"]
            input_t = usage["prompt_tokens"]
            output_t = usage["completion_tokens"]

            # 用 tokenkeeper calculate_cost（从内置价格表）
            cost = calculate_cost(model, input_t, output_t)

            # 记账
            guard.record(
                model=model,
                prompt_tokens=input_t,
                completion_tokens=output_t,
                cost_usd=cost.cost_usd,
                cost_cny=cost.cost_cny,
                latency_ms=elapsed,
                provider="minimax",
            )

            reply = resp["choices"][0]["message"]["content"]
            print(f"  ✅ {model}  ${cost.cost_usd:.6f}  ({elapsed:.0f}ms)")
            print(f"     input={input_t}, output={output_t}")
            print(f"     reply: {reply[:60]!r}")
        except Exception as e:
            print(f"  ❌ {e}")

    return len(test_cases)


def phase2_show_ledger():
    """阶段 2：看账本。"""
    print("\n" + "=" * 60)
    print("📊 阶段 2：账本内容")
    print("=" * 60)

    calls = guard.query()
    print(f"共 {len(calls)} 条记录:")
    for c in calls:
        print(f"  - {c.model:20s}  ${c.cost_usd:.6f}  {c.status}")

    summary = guard.summary(group_by="model")
    print("\n按模型汇总:")
    for row in summary:
        print(
            f"  {row['group_key']:25s}  calls={row['calls']:>3d}  cost=${row['cost_usd']:.6f}"
        )

    total_usd, total_cny = guard.total_cost()
    print(f"\n总成本: ${total_usd:.6f} / ¥{total_cny:.6f}")


def phase3_demo_budget():
    """阶段 3：演示预算熔断。"""
    print("\n" + "=" * 60)
    print("🛑 阶段 3：演示预算熔断")
    print("=" * 60)

    # 设置极低预算
    guard.set_budget(
        daily_limit_usd=0.0005,  # 0.05 美分
        action="block",
    )
    print("   已设日预算 $0.0005，超限 block")

    # 现在已花 ~$0.0001，再调一次会超
    print("\n   再调用一次 minimax M3...")
    try:
        resp = call_minimax("说一句 hi", "MiniMax-M3")
        usage = resp["usage"]
        cost = calculate_cost(
            "MiniMax-M3", usage["prompt_tokens"], usage["completion_tokens"]
        )
        guard.record(
            model="MiniMax-M3",
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            cost_usd=cost.cost_usd,
            cost_cny=cost.cost_cny,
            latency_ms=100,
        )
        print(f"   ✅ 记账成功（cost=${cost.cost_usd:.6f}）")
    except Exception as e:
        print(f"   ❌ 出错: {e}")


def phase4_clear_and_redemo():
    """阶段 4：清账本重新演示（确保看板显示干净数据）。"""
    print("\n" + "=" * 60)
    print("🔄 阶段 4：清账本 + 重新跑 5 次（更戏剧）")
    print("=" * 60)

    guard.uninstall()
    if os.path.exists(demo_db):
        os.remove(demo_db)

    guard.install(db_path=demo_db, project="demo-video", user="presenter")

    # 跑 5 次不同长度的提示
    prompts = [
        "hi",
        "用 5 个词介绍 Python",
        "写一首关于编程的短诗（4 行）",
        "解释量子计算（100 字内）",
        "给我讲个笑话",
    ]

    for prompt in prompts:
        try:
            t0 = time.time()
            resp = call_minimax(prompt, "MiniMax-M3")
            elapsed = (time.time() - t0) * 1000

            usage = resp["usage"]
            input_t = usage["prompt_tokens"]
            output_t = usage["completion_tokens"]
            cost = calculate_cost("MiniMax-M3", input_t, output_t)

            guard.record(
                model="MiniMax-M3",
                prompt_tokens=input_t,
                completion_tokens=output_t,
                cost_usd=cost.cost_usd,
                cost_cny=cost.cost_cny,
                latency_ms=elapsed,
                provider="minimax",
            )

            print(
                f"  ✅ {prompt[:30]!r:30s}  in={input_t:>4d}  out={output_t:>4d}  ${cost.cost_usd:.6f}"
            )
        except Exception as e:
            print(f"  ❌ {e}")


def main():
    """主演示流程。"""
    print("🪶 tokenkeeper × minimax 真实验证 + 演示")
    print("=" * 60)

    setup()
    _ = phase1_real_calls()
    phase2_show_ledger()
    phase3_demo_budget()
    phase4_clear_and_redemo()
    teardown()

    # 最后总结
    print("\n" + "=" * 60)
    print("📊 最终账本")
    print("=" * 60)
    ledger = Ledger(demo_db)
    summary = ledger.summary(group_by="model")
    for row in summary:
        print(
            f"  {row['group_key']:20s}  calls={row['calls']:>3d}  cost=${row['cost_usd']:.6f}"
        )
    total_usd, total_cny = ledger.total_cost()
    print(f"\n总成本: ${total_usd:.6f} / ¥{total_cny:.6f}")
    ledger.close()

    print("\n✅ 演示数据准备完成，看板可立即显示")


if __name__ == "__main__":
    main()
