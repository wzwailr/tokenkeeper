"""tokenkeeper.ledger 自检脚本。

运行方式::

    python scripts/self_check_ledger.py

或::

    python -m scripts.self_check_ledger
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time

# 让脚本能 import tokenkeeper 包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tokenkeeper.ledger import CallRecord, Ledger


def main() -> None:
    """运行 ledger 自检流程。"""
    print("=" * 60)
    print("tokenkeeper.ledger self-check")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        ledger = Ledger(db_path)

        # 1. 插入测试
        print("\n[1] 插入测试:")
        for i in range(5):
            record = CallRecord(
                timestamp=time.time(),
                project="test-app",
                user=f"user-{i % 2}",
                provider="openai",
                model="gpt-4o",
                prompt_tokens=1000 + i * 100,
                completion_tokens=500 + i * 50,
                cost_usd=0.01 * (i + 1),
                cost_cny=0.072 * (i + 1),
                latency_ms=1000 + i * 100,
                status="success",
            )
            rowid = ledger.record(record)
            print(f"    Inserted id={rowid}, model={record.model}")

        # 2. 错误状态
        error_record = CallRecord(
            timestamp=time.time(),
            model="claude-sonnet-4",
            provider="anthropic",
            status="error",
            error="rate limit exceeded",
        )
        ledger.record(error_record)

        # 3. 查询
        print("\n[2] 查询测试:")
        calls = ledger.query()
        print(f"    总记录数: {len(calls)}")
        for c in calls[:3]:
            print(f"    - {c.model} {c.status} cost=${c.cost_usd:.4f}")

        # 4. 按项目筛选
        calls = ledger.query(project="test-app")
        print(f"    project=test-app: {len(calls)} 条")

        # 5. 按模型筛选
        calls = ledger.query(model="claude-sonnet-4")
        print(f"    model=claude-sonnet-4: {len(calls)} 条")

        # 6. 汇总
        print("\n[3] 汇总测试:")
        by_model = ledger.summary(group_by="model")
        for row in by_model:
            print(
                f"    {row['group_key']:>25s}  calls={row['calls']:>3d}  cost=${row['cost_usd']:.4f}"
            )

        by_user = ledger.summary(group_by="user")
        for row in by_user:
            print(f"    user={row['group_key']:>8s}  calls={row['calls']:>3d}")

        # 7. 总成本
        print("\n[4] 总成本:")
        usd, cny = ledger.total_cost()
        print(f"    总成本: ${usd:.4f} / ¥{cny:.4f}")

        # 8. 导出
        print("\n[5] 导出测试:")
        jsonl_path = os.path.join(tmpdir, "export.jsonl")
        n = ledger.export_jsonl(jsonl_path)
        print(f"    JSONL: {n} 行 → {jsonl_path}")

        csv_path = os.path.join(tmpdir, "export.csv")
        n = ledger.export_csv(csv_path)
        print(f"    CSV:   {n} 行 → {csv_path}")

        # 9. 关闭
        ledger.close()

        # 10. 重打开验证持久化
        print("\n[6] 持久化测试:")
        ledger2 = Ledger(db_path)
        print(f"    重打开后记录数: {ledger2.count()}")
        ledger2.close()

        print("\n[OK] self-check 通过")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    main()
