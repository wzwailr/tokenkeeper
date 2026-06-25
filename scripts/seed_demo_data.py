"""灌入演示数据——生成最近 30 天的真实使用场景数据。"""

from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tokenkeeper import guard
from tokenkeeper.ledger import CallRecord
from tokenkeeper.pricing import calculate_cost

# 生成最近 30 天的数据
random.seed(42)
models = [
    ("gpt-4o", 2.50, 10.00, "openai"),
    ("gpt-4o-mini", 0.15, 0.60, "openai"),
    ("claude-sonnet-4", 3.00, 15.00, "anthropic"),
    ("claude-haiku-4", 1.00, 5.00, "anthropic"),
    ("deepseek-chat", 0.14, 0.28, "deepseek"),
    ("qwen-plus", 0.80, 2.00, "alibaba"),
]

db_path = os.path.join(os.path.dirname(__file__), "..", "examples", "demo.db")
if os.path.exists(db_path):
    os.remove(db_path)

guard.install(db_path=db_path, project="ai-assistant", user="alice")

ledger = guard.ledger()

now = time.time()
total_records = 0
print("=== 灌入演示数据 ===")
print(f"DB: {db_path}")
print()

for day in range(30):
    day_offset = 30 - day  # 越近的越多
    day_time = now - day_offset * 86400

    # 每天 5-30 次调用
    num_calls = random.randint(5, 30)

    for _ in range(num_calls):
        model, in_price, out_price, provider = random.choice(models)

        # token 数（按模型分布）
        if "gpt-4" in model and "mini" not in model:
            prompt_tokens = random.randint(500, 5000)
            completion_tokens = random.randint(100, 1500)
        elif "claude-sonnet" in model:
            prompt_tokens = random.randint(1000, 8000)
            completion_tokens = random.randint(200, 2000)
        elif "haiku" in model or "mini" in model:
            prompt_tokens = random.randint(200, 2000)
            completion_tokens = random.randint(50, 500)
        else:
            prompt_tokens = random.randint(500, 4000)
            completion_tokens = random.randint(100, 1000)

        # 偶尔有缓存命中
        cached_tokens = 0
        if "deepseek" in model or "claude" in model:
            if random.random() < 0.3:  # 30% 概率
                cached_tokens = int(prompt_tokens * random.uniform(0.3, 0.8))

        # 计算成本
        cost = calculate_cost(model, prompt_tokens, completion_tokens, cached_tokens)

        # 偶尔有错误
        if random.random() < 0.05:
            status = "error"
            error_msg = random.choice([
                "rate limit exceeded",
                "context_length_exceeded",
                "invalid_api_key",
                "internal_server_error",
            ])
        else:
            status = "success"
            error_msg = None

        # 延迟
        latency_ms = random.uniform(300, 3500)

        # 写入
        record = CallRecord(
            timestamp=day_time + random.uniform(0, 86400),
            project=random.choice(["ai-assistant", "ai-assistant", "ai-assistant", "data-pipeline"]),
            user=random.choice(["alice", "bob", "carol"]),
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost.cost_usd,
            cost_cny=cost.cost_cny,
            latency_ms=latency_ms,
            status=status,
            error=error_msg,
        )
        ledger.record(record)
        total_records += 1

guard.uninstall()

print(f"✅ 已生成 {total_records} 条记录")
print()
total_usd, total_cny = guard.ledger().total_cost() if False else (0, 0)

# 重新打开 ledger 读总数
from tokenkeeper.ledger import Ledger
ledger2 = Ledger(db_path)
total_usd, total_cny = ledger2.total_cost()
print(f"总成本: ${total_usd:.4f} / ¥{total_cny:.4f}")
print(f"调用次数: {ledger2.count()}")
print()
print("按模型:")
for row in ledger2.summary(group_by="model"):
    print(f"  {row['group_key']:20s}  calls={row['calls']:>4d}  cost=${row['cost_usd']:.4f}")
print()
print("按项目:")
for row in ledger2.summary(group_by="project"):
    print(f"  {row['group_key']:20s}  calls={row['calls']:>4d}  cost=${row['cost_usd']:.4f}")
print()
print("按用户:")
for row in ledger2.summary(group_by="user"):
    print(f"  {row['group_key']:20s}  calls={row['calls']:>4d}  cost=${row['cost_usd']:.4f}")
ledger2.close()