"""测试 tokenkeeper 自动拦截 Anthropic SDK（用 minimax 兼容端点）。"""

import os
import time
import anthropic
from tokenkeeper import guard

print("=" * 60)
print("🪶 测试 Anthropic SDK 自动拦截")
print("=" * 60)

# 用 minimax 兼容 Anthropic 端点（您之前验证过这个能用）
api_key = os.environ.get("MINIMAX_API_KEY", "")
print(f"\nkey 长度: {len(api_key)} chars")

client = anthropic.Anthropic(
    base_url="https://api.minimaxi.com/anthropic",
    api_key=api_key,
)

# 安装 tokenkeeper
guard.install(
    db_path=r"D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper\examples\anthropic_test.db",
    project="anthropic-test",
    user="tester",
)

print(f"guard 已安装: {guard.is_installed()}")
print()

print("业务代码 0 改动，调用 client.messages.create():")
t0 = time.time()
resp = client.messages.create(
    model="MiniMax-M3",
    max_tokens=20,
    messages=[{"role": "user", "content": "说 hello 一个词"}],
)
print(f"  ✅ 调用成功 ({time.time() - t0:.2f}s)")
print(f"  model: {resp.model}")
print(f"  usage: input={resp.usage.input_tokens}, output={resp.usage.output_tokens}")

# 检查账本
print()
calls = guard.query()
print(f"账本记录数: {len(calls)}")
if calls:
    c = calls[0]
    print(f"  模型: {c.model}")
    print(f"  input: {c.prompt_tokens}, output: {c.completion_tokens}")
    print(f"  cost: USD ${c.cost_usd:.6f}, CNY ¥{c.cost_cny:.4f}")
    print(f"  latency: {c.latency_ms:.0f}ms")
    print(f"  provider: {c.provider}")
    if c.prompt_tokens > 0:
        print()
        print("✅ 零侵入 Anthropic SDK 验证成功！")
    else:
        print("❌ 账本记录有问题")
else:
    print("❌ 账本是空的——自动拦截没工作")

guard.uninstall()
