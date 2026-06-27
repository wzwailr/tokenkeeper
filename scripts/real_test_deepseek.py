"""真实 DeepSeek 集成测试 — 用 tokenkeeper 监控你自己的 API 调用。

用法::

    export DEEPSEEK_API_KEY=sk-你的key
    python scripts/real_test_deepseek.py

看板::

    tokenkeeper dashboard --db ./scripts/deepseek_test.db
"""

import os
import sys
import time

# 确保能从项目根 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openai
from tokenkeeper import guard

DEMO_DB = os.path.join(os.path.dirname(__file__), "deepseek_test.db")

# 清理上次测试
if os.path.exists(DEMO_DB):
    os.remove(DEMO_DB)

# ================================================================
# 1. 安装 tokenkeeper
# ================================================================
print("=" * 50)
print("1. 安装 tokenkeeper guard")
print("=" * 50)

guard.install(db_path=DEMO_DB, project="deepseek-test", user="me")
guard.set_budget(daily_limit_usd=1.0, action="warn")
print(f"   ✅ DB: {DEMO_DB}")

# ================================================================
# 2. 创建 DeepSeek 客户端（你的 key）
# ================================================================
print("\n" + "=" * 50)
print("2. 创建 DeepSeek 客户端")
print("=" * 50)

api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    print("   ❌ 请先设置: export DEEPSEEK_API_KEY=sk-你的key")
    sys.exit(1)

client = openai.OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com/v1",
)
print("   ✅ 已连接 DeepSeek API")

# ================================================================
# 3. 真实 API 调用 — tokenkeeper 自动记账
# ================================================================
print("\n" + "=" * 50)
print("3. 调用 DeepSeek（tokenkeeper 自动记账）")
print("=" * 50)

calls_data = [
    {"model": "deepseek-chat", "content": "用一句话介绍 tokenkeeper"},
    {"model": "deepseek-reasoner", "content": "1+1等于几？简短回答"},
]

for i, cd in enumerate(calls_data, 1):
    print(f"\n   调用 {i}: {cd['model']}")
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=cd["model"],
            messages=[{"role": "user", "content": cd["content"]}],
            max_tokens=50,
        )
        latency = (time.time() - t0) * 1000
        print(f"   延迟: {latency:.0f}ms")
        print(f"   回复: {resp.choices[0].message.content[:60]}...")
        # 验证 usage 存在
        if hasattr(resp, "usage") and resp.usage:
            print(f"   token: in={resp.usage.prompt_tokens} out={resp.usage.completion_tokens}")
    except Exception as e:
        print(f"   ❌ 失败: {e}")

# ================================================================
# 4. 查账
# ================================================================
print("\n" + "=" * 50)
print("4. 查看账本")
print("=" * 50)

calls = guard.query()
print(f"   共 {len(calls)} 条记录:")
for c in calls:
    print(f"   {c.model:20s}  in={c.prompt_tokens:>5d}  out={c.completion_tokens:>4d}  "
          f"cost=${c.cost_usd:.6f}  status={c.status}")

total_usd, total_cny = guard.total_cost()
print(f"\n   总成本: ${total_usd:.4f} / ¥{total_cny:.4f}")

# ================================================================
# 5. 卸载
# ================================================================
print("\n" + "=" * 50)
print("5. 卸载")
print("=" * 50)
guard.uninstall()
print(f"   ✅ 已卸载 (DB 保留在 {DEMO_DB})")
print(f"\n   启动看板: tokenkeeper dashboard --db {DEMO_DB}")
