"""tokenkeeper × 阿里百炼 GLM-5.2 真实验证。

用法:
    export DASHSCOPE_API_KEY=*** ...}
    python scripts/real_demo_aliyun.py
"""

from __future__ import annotations

import os
import sys
import time

# 必须放在 import tokenkeeper 之前
sys.path.insert(0, r"D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper")

# key 从环境变量读
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
if not API_KEY:
    print("❌ 请设置 DASHSCOPE_API_KEY 环境变量")
    sys.exit(1)

BASE_URL = "https://ws-f55xg8habaxdv2sm.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
DEMO_DB = (
    r"D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper\examples\aliyun_real.db"
)

# 设置 tokenkeeper DB
os.environ["TOKENKEEPER_DB"] = DEMO_DB

import requests
from tokenkeeper import guard
from tokenkeeper.pricing import calculate_cost


def call_model(prompt: str, model: str = "glm-5.2") -> dict:
    """真实调阿里百炼 OpenAI 兼容 API。"""
    r = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main():
    """主演示流程。"""
    print("=" * 70)
    print("🪶 tokenkeeper × 阿里百炼 GLM-5.2 真实验证")
    print("=" * 70)
    print(f"   API: {BASE_URL}")
    print(f"   DB: {DEMO_DB}")
    print()

    # 重置 DB
    if os.path.exists(DEMO_DB):
        os.remove(DEMO_DB)

    guard.install(db_path=DEMO_DB, project="aliyun-demo", user="presenter")
    print("✅ tokenkeeper 已启动")
    print()

    # 测试多个模型
    test_cases = [
        ("glm-5.2", "用一句话介绍 Python"),
        ("glm-5.2", "9*9 等于几？"),
        ("glm-5.2", "列出 3 种水果"),
        ("glm-5.2", "把 hello 翻译成中文"),
        ("glm-5.2", "写首 4 行诗关于编程"),
    ]

    print("=" * 70)
    print(f"📞 真实调用 {len(test_cases)} 次 glm-5.2")
    print("=" * 70)

    total_cost = 0
    total_input = 0
    total_output = 0

    for i, (model, prompt) in enumerate(test_cases, 1):
        print(f"\\n[第 {i} 次] prompt: {prompt!r}")
        t0 = time.time()
        try:
            resp = call_model(prompt, model)
            elapsed = (time.time() - t0) * 1000

            usage = resp["usage"]
            input_t = usage["prompt_tokens"]
            output_t = usage["completion_tokens"]
            cached_t = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            actual_model = resp.get("model", model)
            reply = resp["choices"][0]["message"]["content"]

            # 用 tokenkeeper 价格表计算成本
            cost = calculate_cost(actual_model, input_t, output_t, cached_t)

            # 记账
            guard.record(
                model=actual_model,
                prompt_tokens=input_t,
                completion_tokens=output_t,
                cost_usd=cost.cost_usd,
                cost_cny=cost.cost_cny,
                latency_ms=elapsed,
                provider="aliyun",
            )

            total_cost += cost.cost_usd
            total_input += input_t
            total_output += output_t

            print(f"  ✅ 回复: {reply[:60]!r}")
            print(f"     input={input_t}, output={output_t}, cached={cached_t}")
            print(f"     延迟: {elapsed:.0f}ms, 成本: ${cost.cost_usd:.6f}")

        except Exception as e:
            print(f"  ❌ {e}")

    print()
    print("=" * 70)
    print("📊 tokenkeeper 账本最终状态")
    print("=" * 70)

    calls = guard.query()
    print(f"\\n共 {len(calls)} 条调用:")
    for c in calls:
        print(
            f"  - {c.model:25s}  input={c.prompt_tokens:>4d}  "
            f"output={c.completion_tokens:>4d}  ${c.cost_usd:.6f}  {c.status}"
        )

    print("\\n按模型汇总:")
    summary = guard.summary(group_by="model")
    for row in summary:
        print(
            f"  {row['group_key']:30s}  calls={row['calls']:>3d}  "
            f"cost=${row['cost_usd']:.6f}"
        )

    total_usd, total_cny = guard.total_cost()
    print(f"\\n总成本: ${total_usd:.6f} / ¥{total_cny:.6f}")
    print(f"总 input tokens: {total_input}")
    print(f"总 output tokens: {total_output}")

    # 测试限额熔断
    print()
    print("=" * 70)
    print("🛑 演示限额熔断")
    print("=" * 70)

    guard.set_budget(
        daily_limit_usd=0.001,  # 极低，立刻超
        action="block",
    )
    print("   设日预算 $0.001（必然超）")
    print("   下次调用会触发 BudgetExceededError:")

    try:
        resp = call_model("hi", "glm-5.2")
        cost = calculate_cost(
            "glm-5.2",
            resp["usage"]["prompt_tokens"],
            resp["usage"]["completion_tokens"],
        )
        guard.record(
            model="glm-5.2",
            prompt_tokens=resp["usage"]["prompt_tokens"],
            completion_tokens=resp["usage"]["completion_tokens"],
            cost_usd=cost.cost_usd,
            cost_cny=cost.cost_cny,
            latency_ms=100,
        )
        print("   ❌ 应该被阻断但没阻断！")
    except Exception as e:
        print(f"   ✅ 阻断成功: {type(e).__name__}")
        print(f"      原因: {e}")

    guard.uninstall()
    print()
    print("=" * 70)
    print("✅ 验证完成")
    print(f"   看板数据位置: {DEMO_DB}")
    print(f"   启动看板: export TOKENKEEPER_DB={DEMO_DB}")
    print("              tokenkeeper dashboard")
    print("=" * 70)


if __name__ == "__main__":
    main()
