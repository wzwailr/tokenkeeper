"""tokenkeeper 集成层扩展测试 — 测试 pricing / ledger / anthropic 辅助函数。"""

from __future__ import annotations

import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch


class TestPricingIntegration(unittest.TestCase):
    """pricing 模块测试。"""

    def test_calculate_cost_gpt4o(self):
        from tokenkeeper.pricing import calculate_cost
        cost = calculate_cost("gpt-4o", 1000, 500)
        self.assertGreater(cost.cost_usd, 0)

    def test_unknown_model_zero_cost(self):
        from tokenkeeper.pricing import calculate_cost
        cost = calculate_cost("no-such-model", 1000, 500)
        self.assertEqual(cost.cost_usd, 0.0)

    def test_list_models(self):
        from tokenkeeper.pricing import list_models
        models = list_models()
        self.assertGreater(len(models), 30)

    def test_custom_pricing_register(self):
        from tokenkeeper.pricing import register_custom_pricing, ModelPricing, calculate_cost
        register_custom_pricing(
            "my-test-model", ModelPricing(input_per_1m=1.0, output_per_1m=2.0, provider="test"),
        )
        cost = calculate_cost("my-test-model", 1_000_000, 500_000)
        self.assertAlmostEqual(cost.cost_usd, 2.0, places=1)


class TestAnthropicHelpers(unittest.TestCase):
    """anthropic 辅助函数测试。"""

    def test_estimate_tokens(self):
        from tokenkeeper.integrations.anthropic import _estimate_input_tokens
        tokens = _estimate_input_tokens([{"role": "user", "content": "Hello"}])
        self.assertGreater(tokens, 0)

    def test_estimate_tokens_with_system(self):
        from tokenkeeper.integrations.anthropic import _estimate_input_tokens
        t1 = _estimate_input_tokens([{"role": "user", "content": "Hi"}])
        t2 = _estimate_input_tokens([{"role": "user", "content": "Hi"}], system="Long system prompt")
        self.assertGreater(t2, t1)

    def test_extract_model(self):
        from tokenkeeper.integrations.anthropic import _extract_model
        resp = MagicMock()
        resp.model = "claude-sonnet-4-20250514"
        self.assertEqual(_extract_model(resp), "claude-sonnet-4-20250514")

    def test_extract_model_none(self):
        from tokenkeeper.integrations.anthropic import _extract_model
        resp = MagicMock(spec=[])
        self.assertIsNone(_extract_model(resp))

    def test_extract_usage(self):
        from tokenkeeper.integrations.anthropic import _extract_usage
        resp = MagicMock()
        resp.usage = MagicMock(input_tokens=100, output_tokens=50, cache_read_input_tokens=0)
        prompt, comp, _total = _extract_usage(resp)
        self.assertEqual(prompt, 100)
        self.assertEqual(comp, 50)


class TestLedgerEdgeCases(unittest.TestCase):
    """Ledger 边界条件。"""

    def test_empty_db_returns_empty(self):
        from tokenkeeper.ledger import Ledger
        with tempfile.TemporaryDirectory() as tmp:
            import os
            db_path = os.path.join(tmp, "empty.db")
            with Ledger(db_path) as ledger:
                self.assertEqual(len(ledger.query()), 0)

    def test_closed_ledger_returns_none(self):
        from tokenkeeper.ledger import Ledger, CallRecord
        with tempfile.TemporaryDirectory() as tmp:
            import os
            db_path = os.path.join(tmp, "test.db")
            ledger = Ledger(db_path)
            ledger.close()
            result = ledger.record(CallRecord(timestamp=time.time(), model="gpt-4o"))
            self.assertIsNone(result)

    def test_record_batch(self):
        from tokenkeeper.ledger import Ledger, CallRecord
        with tempfile.TemporaryDirectory() as tmp:
            import os
            db_path = os.path.join(tmp, "test.db")
            with Ledger(db_path) as ledger:
                calls = [
                    CallRecord(timestamp=time.time(), model="gpt-4o", cost_usd=0.01),
                    CallRecord(timestamp=time.time(), model="gpt-4o-mini", cost_usd=0.001),
                ]
                count = ledger.record_batch(calls)
                self.assertEqual(count, 2)


class TestGracefulDegradation(unittest.TestCase):
    """降级模式：patch 失败不影响服务。"""

    def setUp(self):
        from tokenkeeper import guard
        if guard.is_installed():
            guard.uninstall()

    def test_install_succeeds_when_openai_patch_fails(self):
        with patch("tokenkeeper.integrations.openai_compat.install",
                   side_effect=Exception("boom")):
            from tokenkeeper import guard
            with tempfile.TemporaryDirectory() as tmp:
                import os
                db_path = os.path.join(tmp, "test.db")
                guard.install(db_path=db_path, auto_patch_openai=True)
                self.assertTrue(guard.is_installed())
                guard.uninstall()

    def test_install_succeeds_when_anthropic_patch_fails(self):
        with patch("tokenkeeper.integrations.anthropic.install",
                   side_effect=Exception("boom")):
            from tokenkeeper import guard
            with tempfile.TemporaryDirectory() as tmp:
                import os
                db_path = os.path.join(tmp, "test.db")
                guard.install(db_path=db_path, auto_patch_openai=True)
                self.assertTrue(guard.is_installed())
                guard.uninstall()


if __name__ == "__main__":
    unittest.main()
