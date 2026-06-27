"""测试 tokenkeeper 自动拦截 OpenAI SDK（用 minimax 作为兼容后端）。"""

import os
from pathlib import Path
import openai
from tokenkeeper import guard
import time

ROOT = Path(__file__).resolve().parents[1]

print("=" * 60)
print("🪶 测试 OpenAI 自动拦截")
print("=" * 60)

# 关键：openai 客户端指向 minimax（兼容）
api_key = os.environ.get("MINIMAX_API_KEY", "")
print(f"\nkey 长度: {len(api_key)} chars")

client = openai.OpenAI(
    api_key=api_key,
    base_url="https://api.minimaxi.com/v1",
)

# 安装 tokenkeeper（应该自动 patch openai SDK）
guard.install(
    db_path=str(ROOT / "examples" / "auto_test.db"),
    project="auto-test",
    user="tester",
)

print(f"guard 已安装: {guard.is_installed()}")
print()

print("业务代码 0 改动，调用 openai.chat.completions.create():")
t0 = time.time()
resp = client.chat.completions.create(
    model="MiniMax-M3",
    messages=[{"role": "user", "content": "说 hello 一个词"}],
    max_tokens=10,
)
print(f"  ✅ 调用成功 ({time.time() - t0:.2f}s)")
print(f"  回复: {resp.choices[0].message.content!r}")
print(
    f"  usage: prompt={resp.usage.prompt_tokens}, completion={resp.usage.completion_tokens}"
)
print()

# 检查账本有没有自动记录
calls = guard.query()
print(f"账本记录数: {len(calls)}")
if calls:
    c = calls[0]
    print(f"  模型: {c.model}")
    print(f"  input: {c.prompt_tokens}, output: {c.completion_tokens}")
    print(f"  cost: USD ${c.cost_usd:.6f}, CNY ¥{c.cost_cny:.4f}")
    print(f"  latency: {c.latency_ms:.0f}ms")
    print(f"  provider: {c.provider}")
    if c.prompt_tokens > 0 and c.model == "MiniMax-M3":
        print()
        print("✅ 零侵入接入验证成功！自动记账 OK！")
    else:
        print()
        print("❌ 账本记录有问题——需要排查")
else:
    print()
    print("❌ 账本是空的——自动拦截没工作")

guard.uninstall()
