"""tokenkeeper × minimax 验证（key 从 prompt 读，绕过 Hermes redact）。"""

import sys
import os
import time
import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 用 getpass 让您输入（不会显示在屏幕上，也不会被 Hermes redact）
print("=" * 60)
print("🪶 tokenkeeper × minimax 真实验证")
print("=" * 60)
print()

try:
    api_key = getpass.getpass("请粘贴您的 minimax API key（输入时不显示）: ")
except Exception:
    # 在某些环境 getpass 不可用
    print("getpass 不可用，请直接粘贴 key 然后回车:")
    api_key = input().strip()

print(f"\nkey 长度: {len(api_key)} chars")

if len(api_key) < 50:
    print("❌ key 太短（应该 100+ 字符），可能被截断了")
    print("   请确认完整粘贴，不要在中间换行或截断")
    sys.exit(1)

base = "https://api.minimaxi.com/v1"
demo_db = str(ROOT / "examples" / "minimax_real.db")
if os.path.exists(demo_db):
    os.remove(demo_db)

from tokenkeeper import guard
from tokenkeeper.ledger import Ledger
from tokenkeeper.pricing import calculate_cost

os.environ["TOKENKEEPER_DB"] = demo_db
guard.install(db_path=demo_db, project="minimax-demo", user="tester")

prompts = [
    "用一句话介绍 Python",
    "9*9 等于几？",
    "列出 3 种水果",
    "把 hello 翻译成中文",
    "讲个笑话",
]

print(f"\n=== 连续 {len(prompts)} 次真实 minimax M3 调用 ===\n")

total_cost = 0
for i, prompt in enumerate(prompts, 1):
    t0 = time.time()
    try:
        import requests

        r = requests.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "MiniMax-M3",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        elapsed = (time.time() - t0) * 1000
        if r.status_code == 200:
            data = r.json()
            usage = data["usage"]
            cost = calculate_cost(
                "MiniMax-M3", usage["prompt_tokens"], usage["completion_tokens"]
            )
            guard.record(
                model="MiniMax-M3",
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                cost_usd=cost.cost_usd,
                cost_cny=cost.cost_cny,
                latency_ms=elapsed,
                provider="minimax",
            )
            total_cost += cost.cost_usd
            print(
                f"  ✅ [{i}] HTTP 200 ({elapsed:.0f}ms)  "
                f"in={usage['prompt_tokens']} out={usage['completion_tokens']}  "
                f"${cost.cost_usd:.6f}"
            )
            print(f"      reply: {data['choices'][0]['message']['content'][:60]!r}")
        else:
            print(f"  ❌ [{i}] HTTP {r.status_code}: {r.text[:80]}")
    except Exception as e:
        print(f"  ❌ [{i}] {type(e).__name__}: {e}")

guard.uninstall()
print(f"\n总成本: ${total_cost:.6f}")
print(f"DB: {demo_db}")

ledger = Ledger(demo_db)
print(f"\n账本共 {ledger.count()} 条记录")
for row in ledger.summary(group_by="model"):
    print(f"  {row['group_key']}  calls={row['calls']}  cost=${row['cost_usd']:.6f}")
ledger.close()
