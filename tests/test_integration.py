"""tokenkeeper 集成测试 — 测试核心集成路径。"""

from __future__ import annotations

import os
import time
import tempfile
import unittest
from unittest.mock import patch


def _make_record(
    model="gpt-4o",
    prompt=100,
    completion=50,
    cost_usd=0.005,
    project="test",
    user="tester",
    status="success",
):
    """构造 CallRecord 对象。"""
    from tokenkeeper.ledger import CallRecord

    return CallRecord(
        timestamp=time.time(),
        model=model,
        provider="openai",
        prompt_tokens=prompt,
        completion_tokens=completion,
        cost_usd=cost_usd,
        cost_cny=cost_usd * 7.2,
        latency_ms=500,
        project=project,
        user=user,
        status=status,
    )


class TestLedgerIntegration(unittest.TestCase):
    """Ledger 读写集成测试。"""

    def test_record_and_query(self):
        """手动记账 → 查询 → 统计。"""
        from tokenkeeper.ledger import Ledger

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            with Ledger(db_path) as ledger:
                rowid = ledger.record(_make_record())
                self.assertIsNotNone(rowid)
                self.assertIsInstance(rowid, int)

                # summary 返回 list[dict]
                stats = ledger.summary()
                self.assertIsInstance(stats, list)
                self.assertGreaterEqual(len(stats), 1)

                # query 返回 list[CallRecord]
                results = ledger.query(limit=10)
                self.assertGreaterEqual(len(results), 1)
                self.assertEqual(results[0].model, "gpt-4o")
                self.assertEqual(results[0].project, "test")

                # total_cost 返回 tuple[float, float]
                cost_usd, cost_cny = ledger.total_cost()
                self.assertGreater(cost_usd, 0)

    def test_multiple_records_and_filtering(self):
        """多条记录 + 按 project 筛选。"""
        from tokenkeeper.ledger import Ledger

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            with Ledger(db_path) as ledger:
                ledger.record(_make_record(model="gpt-4o", project="proj-a", user="u1"))
                ledger.record(
                    _make_record(model="gpt-4o-mini", project="proj-b", user="u1")
                )
                ledger.record(_make_record(model="gpt-4o", project="proj-a", user="u2"))

                self.assertEqual(len(ledger.query(limit=10)), 3)
                self.assertEqual(len(ledger.query(limit=10, project="proj-a")), 2)
                self.assertEqual(len(ledger.query(limit=10, project="proj-b")), 1)

                cost_usd, _ = ledger.total_cost()
                self.assertGreater(cost_usd, 0)

    def test_summary_by_dimension(self):
        """按不同维度汇总。"""
        from tokenkeeper.ledger import Ledger

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            with Ledger(db_path) as ledger:
                ledger.record(_make_record(model="gpt-4o", project="p1"))
                ledger.record(_make_record(model="gpt-4o-mini", project="p1"))
                ledger.record(_make_record(model="gpt-4o", project="p2"))

                # 按 model 汇总
                by_model = ledger.summary(group_by="model")
                self.assertGreaterEqual(len(by_model), 2)

                # 按 project 汇总
                by_project = ledger.summary(group_by="project")
                self.assertEqual(len(by_project), 2)

                # 按 user 汇总
                by_user = ledger.summary(group_by="user")
                self.assertGreaterEqual(len(by_user), 1)


class TestGuardIntegration(unittest.TestCase):
    """Guard 预算检查集成测试。"""

    def setUp(self):
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    def test_budget_block(self):
        """超限 block 抛 BudgetExceededError。"""
        from tokenkeeper import guard, BudgetExceededError

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(
                db_path=db_path, project="test", user="tester", auto_patch_openai=False
            )
            guard.set_budget(daily_limit_usd=0.01, action="block")

            ledger = guard.ledger()
            ledger.record(_make_record(cost_usd=0.02, project="test", user="tester"))

            gi = guard.guard_instance()
            with self.assertRaises(BudgetExceededError):
                gi.check(estimated_cost=0.01, project="test", user="tester")

            guard.uninstall()

    def test_budget_warn(self):
        """超限 warn 不抛异常。"""
        from tokenkeeper import guard

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(
                db_path=db_path, project="test", user="tester", auto_patch_openai=False
            )
            guard.set_budget(daily_limit_usd=0.01, action="warn")

            ledger = guard.ledger()
            ledger.record(_make_record(cost_usd=0.02, project="test", user="tester"))

            gi = guard.guard_instance()
            gi.check(estimated_cost=0.01, project="test", user="tester")

            guard.uninstall()

    def test_under_budget_passes(self):
        """预算内正常通过。"""
        from tokenkeeper import guard

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(
                db_path=db_path, project="test", user="tester", auto_patch_openai=False
            )
            guard.set_budget(daily_limit_usd=10.0, action="block")

            gi = guard.guard_instance()
            gi.check(estimated_cost=0.01, project="test", user="tester")

            guard.uninstall()


class TestErrorIsolation(unittest.TestCase):
    """错误隔离：patch 失败不影响 install。"""

    def setUp(self):
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    def test_openai_patch_failure_doesnt_block_install(self):
        """OpenAI patch 抛异常，install() 仍完成。"""
        with patch(
            "tokenkeeper.integrations.openai_compat.install",
            side_effect=Exception("模拟 patch 失败"),
        ):
            from tokenkeeper import guard

            with tempfile.TemporaryDirectory() as tmp:
                db_path = os.path.join(tmp, "test.db")
                guard.install(db_path=db_path, auto_patch_openai=True)
                self.assertTrue(guard.is_installed())
                guard.uninstall()

    def test_anthropic_patch_failure_doesnt_block_install(self):
        """Anthropic patch 抛异常，install() 仍完成。"""
        with patch(
            "tokenkeeper.integrations.anthropic.install",
            side_effect=Exception("模拟 Anthropic patch 失败"),
        ):
            from tokenkeeper import guard

            with tempfile.TemporaryDirectory() as tmp:
                db_path = os.path.join(tmp, "test.db")
                guard.install(db_path=db_path, auto_patch_openai=True)
                self.assertTrue(guard.is_installed())
                guard.uninstall()

    def test_both_patches_fail_still_installs(self):
        """OpenAI 和 Anthropic 都失败，install() 仍完成。"""
        with (
            patch(
                "tokenkeeper.integrations.openai_compat.install",
                side_effect=Exception("fail"),
            ),
            patch(
                "tokenkeeper.integrations.anthropic.install",
                side_effect=Exception("fail"),
            ),
        ):
            from tokenkeeper import guard

            with tempfile.TemporaryDirectory() as tmp:
                db_path = os.path.join(tmp, "test.db")
                guard.install(db_path=db_path, auto_patch_openai=True)
                self.assertTrue(guard.is_installed())
                guard.uninstall()


class TestGuardInstallUninstall(unittest.TestCase):
    """install / uninstall 幂等性。"""

    def setUp(self):
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    def test_install_idempotent(self):
        """重复 install 不报错。"""
        from tokenkeeper import guard

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(db_path=db_path, auto_patch_openai=False)
            self.assertTrue(guard.is_installed())
            guard.install(db_path=db_path, auto_patch_openai=False)
            self.assertTrue(guard.is_installed())
            guard.uninstall()
            self.assertFalse(guard.is_installed())

    def test_uninstall_then_reinstall(self):
        """卸载后重新安装。"""
        from tokenkeeper import guard

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(db_path=db_path, auto_patch_openai=False)
            self.assertTrue(guard.is_installed())
            guard.uninstall()
            self.assertFalse(guard.is_installed())
            guard.install(db_path=db_path, auto_patch_openai=False)
            self.assertTrue(guard.is_installed())
            guard.uninstall()


class TestBudgetScopeIntegration(unittest.TestCase):
    """预算 scope 集成测试。"""

    def setUp(self):
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    def test_project_level_budget(self):
        """项目级别预算互不影响。"""
        from tokenkeeper import guard, BudgetExceededError

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(db_path=db_path, auto_patch_openai=False)

            guard.set_budget(
                scope="project",
                scope_key="proj-a",
                daily_limit_usd=0.01,
                action="block",
            )

            ledger = guard.ledger()
            ledger.record(_make_record(cost_usd=0.02, project="proj-a", user="u1"))

            gi = guard.guard_instance()
            with self.assertRaises(BudgetExceededError):
                gi.check(estimated_cost=0.01, project="proj-a", user="u1")

            gi.check(estimated_cost=0.90, project="proj-b", user="u1")

            guard.uninstall()

    def test_user_level_budget(self):
        """用户级别预算互不影响。"""
        from tokenkeeper import guard, BudgetExceededError

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(db_path=db_path, auto_patch_openai=False)

            guard.set_budget(
                scope="user", scope_key="alice", daily_limit_usd=0.01, action="block"
            )

            ledger = guard.ledger()
            ledger.record(_make_record(cost_usd=0.02, project="p", user="alice"))

            gi = guard.guard_instance()
            with self.assertRaises(BudgetExceededError):
                gi.check(estimated_cost=0.01, project="p", user="alice")

            gi.check(estimated_cost=0.90, project="p", user="bob")

            guard.uninstall()


if __name__ == "__main__":
    unittest.main()
