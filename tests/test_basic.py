"""tokenkeeper 基础测试套件。

可用 pytest 或 unittest 跑。

pytest::

    pytest tests/test_basic.py -v

unittest::

    python -m unittest tests.test_basic -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

# 让测试能 import tokenkeeper
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tokenkeeper.pricing import (
    ModelPricing,
    CostBreakdown,
    calculate_cost,
    get_pricing,
    list_models,
    register_custom_pricing,
)
from tokenkeeper.ledger import CallRecord, Ledger
from tokenkeeper.guard import Budget, BudgetExceededError, Guard, GuardDecision


# ====================================================================
# 辅助：兼容 pytest 和 unittest 的 assert
# ====================================================================

def _approx(a, b, rel=1e-4):
    """简易 approx（pytest 没装也能用）。"""
    if b == 0:
        return abs(a) < rel
    return abs(a - b) / abs(b) <= rel


# ====================================================================
# Fixtures（unittest 风格用 setUp）
# ====================================================================


def make_temp_db():
    """创建临时 DB 路径。"""
    tmpdir = tempfile.mkdtemp()
    return os.path.join(tmpdir, "test.db"), tmpdir


# ====================================================================
# pricing 测试
# ====================================================================


class TestPricing(unittest.TestCase):
    """价格表与成本计算测试。"""

    def test_list_models_not_empty(self):
        """内置模型列表非空。"""
        models = list_models()
        self.assertGreater(len(models), 0)
        self.assertIn("gpt-4o", models)
        self.assertIn("claude-sonnet-4", models)

    def test_list_models_by_provider(self):
        """按提供商筛选。"""
        openai_models = list_models(provider="openai")
        for m in openai_models:
            self.assertTrue(m.startswith(("gpt-", "o1", "o3", "o4")))

    def test_get_pricing_known(self):
        """已知模型能查到价格。"""
        p = get_pricing("gpt-4o")
        self.assertIsNotNone(p)
        self.assertEqual(p.input_per_1m, 2.50)
        self.assertEqual(p.output_per_1m, 10.00)

    def test_get_pricing_unknown_returns_none(self):
        """未知模型返回 None，不抛异常。"""
        self.assertIsNone(get_pricing("unknown-model-xyz"))

    def test_calculate_cost_basic(self):
        """基础成本计算。"""
        cost = calculate_cost("gpt-4o", prompt_tokens=1_000_000, completion_tokens=500_000)
        # input 1M * $2.50 + output 500K * $10 = $2.50 + $5 = $7.50
        self.assertTrue(_approx(cost.cost_usd, 7.50))
        self.assertGreater(cost.cost_cny, 0)

    def test_calculate_cost_unknown_model_zero(self):
        """未知模型成本为 0。"""
        cost = calculate_cost("unknown-model", prompt_tokens=1000, completion_tokens=500)
        self.assertEqual(cost.cost_usd, 0.0)
        self.assertEqual(cost.cost_cny, 0.0)

    def test_calculate_cost_with_cache(self):
        """缓存命中按缓存价算。"""
        cost_with = calculate_cost("deepseek-chat", 1000, 500, cached_tokens=800)
        cost_without = calculate_cost("deepseek-chat", 1000, 500, cached_tokens=0)
        self.assertLess(cost_with.cost_usd, cost_without.cost_usd)

    def test_calculate_cost_negative_raises(self):
        """负数 token 抛 ValueError。"""
        with self.assertRaises(ValueError):
            calculate_cost("gpt-4o", -1, 0)
        with self.assertRaises(ValueError):
            calculate_cost("gpt-4o", 0, -1)

    def test_calculate_cost_cached_exceeds_prompt_raises(self):
        """cached_tokens > prompt_tokens 在 Anthropic 模式下是合法的。

        Anthropic SDK 的 input_tokens 不含 cache，cache_read 独立计费，
        所以 cached_tokens > prompt_tokens 是正常的（Anthropic 模式）。
        OpenAI 模式 cached_tokens 是 prompt_tokens 的子集。
        pricing.calculate_cost 通过 cached > prompt 自动判定为 Anthropic 模式。
        """
        # Anthropic 模式：cached > prompt 是合法的，按独立累加计费
        cost = calculate_cost("claude-sonnet-4", prompt_tokens=100, completion_tokens=50, cached_tokens=200)
        self.assertGreater(cost.cost_usd, 0)
        self.assertEqual(cost.cached_tokens, 200)
        self.assertEqual(cost.prompt_tokens, 100)

    def test_register_custom_pricing(self):
        """注册自定义价格。"""
        register_custom_pricing(
            "test-custom-model-unique-name",
            ModelPricing(input_per_1m=1.0, output_per_1m=2.0, provider="test"),
        )
        p = get_pricing("test-custom-model-unique-name")
        self.assertIsNotNone(p)
        self.assertEqual(p.input_per_1m, 1.0)

    def test_model_pricing_negative_raises(self):
        """ModelPricing 负数字段抛 ValueError。"""
        with self.assertRaises(ValueError):
            ModelPricing(input_per_1m=-1.0, output_per_1m=1.0)
        with self.assertRaises(ValueError):
            ModelPricing(input_per_1m=1.0, output_per_1m=-1.0)


# ====================================================================
# ledger 测试
# ====================================================================


class TestLedger(unittest.TestCase):
    """SQLite 账本测试。"""

    def setUp(self):
        """每个测试前创建临时 DB。"""
        self.db_path, self.tmpdir = make_temp_db()
        self.ledger = Ledger(self.db_path)

    def tearDown(self):
        """每个测试后关闭并清理。"""
        try:
            self.ledger.close()
        except Exception:
            pass

    def test_record_and_query(self):
        """记录 + 查询。"""
        record = CallRecord(
            timestamp=time.time(),
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=0.0075,
        )
        rowid = self.ledger.record(record)
        self.assertIsNotNone(rowid)

        calls = self.ledger.query()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].model, "gpt-4o")

    def test_query_with_filters(self):
        """按 model/project 筛选。"""
        now = time.time()
        for i, model in enumerate(["gpt-4o", "claude-sonnet-4", "gpt-4o"]):
            self.ledger.record(CallRecord(
                timestamp=now + i,
                project="app-a" if i < 2 else "app-b",
                model=model,
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.01,
            ))

        # 按模型
        gpt_calls = self.ledger.query(model="gpt-4o")
        self.assertEqual(len(gpt_calls), 2)

        # 按项目
        app_a_calls = self.ledger.query(project="app-a")
        self.assertEqual(len(app_a_calls), 2)

    def test_summary_by_model(self):
        """按模型汇总。"""
        for _ in range(3):
            self.ledger.record(CallRecord(
                timestamp=time.time(),
                model="gpt-4o",
                prompt_tokens=100,
                completion_tokens=50,
                cost_usd=0.01,
            ))
        self.ledger.record(CallRecord(
            timestamp=time.time(),
            model="claude-sonnet-4",
            prompt_tokens=200,
            completion_tokens=100,
            cost_usd=0.02,
        ))

        summary = self.ledger.summary(group_by="model")
        self.assertEqual(len(summary), 2)
        # 按 cost_usd 降序
        self.assertGreaterEqual(summary[0]["cost_usd"], summary[1]["cost_usd"])

    def test_total_cost(self):
        """总成本。"""
        self.ledger.record(CallRecord(
            timestamp=time.time(), model="gpt-4o", cost_usd=0.05,
        ))
        self.ledger.record(CallRecord(
            timestamp=time.time(), model="claude-sonnet-4", cost_usd=0.10,
        ))

        total_usd, total_cny = self.ledger.total_cost()
        self.assertTrue(_approx(total_usd, 0.15))
        # 至少 USD > 0
        self.assertGreater(total_usd, 0)

    def test_export_csv(self):
        """导出 CSV。"""
        self.ledger.record(CallRecord(
            timestamp=time.time(),
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
        ))

        csv_path = os.path.join(self.tmpdir, "export.csv")
        n = self.ledger.export_csv(csv_path)
        self.assertEqual(n, 1)
        self.assertTrue(os.path.exists(csv_path))
        with open(csv_path, "r", encoding="utf-8") as f:
            self.assertIn("gpt-4o", f.read())

    def test_export_jsonl(self):
        """导出 JSONL。"""
        import json
        self.ledger.record(CallRecord(
            timestamp=time.time(),
            model="gpt-4o",
            cost_usd=0.01,
        ))

        jsonl_path = os.path.join(self.tmpdir, "export.jsonl")
        n = self.ledger.export_jsonl(jsonl_path)
        self.assertEqual(n, 1)
        with open(jsonl_path, "r", encoding="utf-8") as f:
            data = json.loads(f.readline())
            self.assertEqual(data["model"], "gpt-4o")

    def test_callrecord_invalid_status(self):
        """CallRecord 非法 status 抛 ValueError。"""
        with self.assertRaises(ValueError):
            CallRecord(timestamp=time.time(), model="x", status="invalid")

    def test_callrecord_auto_total_tokens(self):
        """CallRecord 自动计算 total_tokens。"""
        record = CallRecord(
            timestamp=time.time(),
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        self.assertEqual(record.total_tokens, 1500)


# ====================================================================
# guard 测试
# ====================================================================


class TestGuard(unittest.TestCase):
    """限额熔断器测试。"""

    def setUp(self):
        """每个测试前创建新 ledger 和 guard。"""
        self.db_path, self.tmpdir = make_temp_db()
        self.ledger = Ledger(self.db_path)
        self.guard = Guard(self.ledger)

    def tearDown(self):
        """清理。"""
        try:
            self.ledger.close()
        except Exception:
            pass

    def test_no_budget_always_allow(self):
        """没设预算 = 永远 allow。"""
        for _ in range(10):
            decision = self.guard.check(estimated_cost=100.0)
            self.assertEqual(decision, GuardDecision.ALLOW)

    def test_per_call_budget_block(self):
        """单次预算超限 block 抛异常。"""
        self.guard.set_budget(Budget(
            scope="global", scope_key=None,
            per_call_limit_usd=1.0, action="block",
        ))

        self.assertEqual(self.guard.check(0.5), GuardDecision.ALLOW)

        with self.assertRaises(BudgetExceededError):
            self.guard.check(2.0)

    def test_per_call_budget_warn(self):
        """单次预算超限 warn 只警告。"""
        self.guard.set_budget(Budget(
            scope="global", scope_key=None,
            per_call_limit_usd=1.0, action="warn",
        ))

        decision = self.guard.check(2.0)
        self.assertEqual(decision, GuardDecision.WARN)

    def test_project_scope(self):
        """项目级 scope 只匹配对应项目。"""
        self.guard.set_budget(Budget(
            scope="project", scope_key="app-a",
            per_call_limit_usd=1.0, action="block",
        ))

        with self.assertRaises(BudgetExceededError):
            self.guard.check(2.0, project="app-a")

        self.assertEqual(
            self.guard.check(2.0, project="app-b"),
            GuardDecision.ALLOW,
        )

    def test_budget_invalid_scope(self):
        """非法 scope 抛 ValueError。"""
        with self.assertRaises(ValueError):
            Budget(scope="invalid", scope_key=None)

    def test_budget_invalid_action(self):
        """非法 action 抛 ValueError。"""
        with self.assertRaises(ValueError):
            Budget(scope="global", scope_key=None, action="invalid")

    def test_budget_project_requires_key(self):
        """project scope 必须有 scope_key。"""
        with self.assertRaises(ValueError):
            Budget(scope="project", scope_key=None)


# ====================================================================
# 集成测试
# ====================================================================


class TestGracefulImport(unittest.TestCase):
    """测试优雅降级：即使 ledger 安装有 openai/anthropic，import 也不挂。"""

    def test_can_install_and_uninstall(self):
        """guard.install 和 uninstall 能跑（这是 CI 验证的核心）。"""
        # 用临时 DB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            from tokenkeeper import guard
            guard.install(db_path=db_path, project="test", user="tester")
            self.assertTrue(guard.is_installed())
            guard.uninstall()
            self.assertFalse(guard.is_installed())


class TestCoreIntegration(unittest.TestCase):
    """core 模块集成测试。"""

    def setUp(self):
        """每个测试前重置单例。"""
        from tokenkeeper import guard
        if guard.is_installed():
            guard.uninstall()

    def tearDown(self):
        """每个测试后清理。"""
        from tokenkeeper import guard
        if guard.is_installed():
            guard.uninstall()

    def test_install_uninstall_cycle(self):
        """install → uninstall 循环。"""
        from tokenkeeper import guard
        db_path, _ = make_temp_db()

        guard.install(db_path=db_path, project="test")
        self.assertTrue(guard.is_installed())

        guard.uninstall()
        self.assertFalse(guard.is_installed())

    def test_record_query_via_guard(self):
        """通过 guard 单例 record + query。"""
        from tokenkeeper import guard
        db_path, _ = make_temp_db()

        guard.install(db_path=db_path, project="test")

        guard.record(model="gpt-4o", prompt_tokens=100, completion_tokens=50, cost_usd=0.001)
        calls = guard.query()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].project, "test")

    def test_install_idempotent(self):
        """重复 install 是幂等的。"""
        from tokenkeeper import guard
        db_path, _ = make_temp_db()

        guard.install(db_path=db_path, project="test")
        first_ledger = guard.ledger()
        guard.install(db_path=db_path, project="test")  # 重复
        second_ledger = guard.ledger()
        self.assertIs(first_ledger, second_ledger)

    def test_set_budget_via_guard(self):
        """通过 guard 单例 set_budget。"""
        from tokenkeeper import guard
        db_path, _ = make_temp_db()

        guard.install(db_path=db_path, project="test")
        guard.set_budget(daily_limit_usd=10.0, action="warn")
        self.assertEqual(len(guard.guard_instance().get_budgets()), 1)

    def test_summary_via_guard(self):
        """通过 guard 单例 summary。"""
        from tokenkeeper import guard
        db_path, _ = make_temp_db()

        guard.install(db_path=db_path, project="test")
        guard.record(model="gpt-4o", cost_usd=0.01)

        summary = guard.summary(group_by="model")
        self.assertEqual(len(summary), 1)


# ====================================================================
# 测试入口
# ====================================================================


if __name__ == "__main__":
    unittest.main(verbosity=2)