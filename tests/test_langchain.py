"""LangChain callback 单元测试（mock langchain）。"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock, patch


class TestLangChainCallback(unittest.TestCase):
    """测试 TokenKeeperCallbackHandler。"""

    def setUp(self):
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_callback_can_be_created(self):
        """callback 可以在不装 langchain 的情况下导入和实例化。"""
        # 注：实际需要 langchain-core 才能运行，这里只测 import 路径
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        self.assertTrue(callable(TokenKeeperCallbackHandler))

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_extract_model_from_llm_output(self):
        """从 llm_output 提取 model。"""
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        fake_resp = MagicMock()
        fake_resp.llm_output = {
            "model_name": "gpt-4o",
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

        model = TokenKeeperCallbackHandler._extract_model(fake_resp)
        self.assertEqual(model, "gpt-4o")

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_extract_usage_from_llm_output(self):
        """从 llm_output 提取 token usage。"""
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        fake_resp = MagicMock()
        fake_resp.llm_output = {
            "token_usage": {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
            }
        }

        p, c, t = TokenKeeperCallbackHandler._extract_usage(fake_resp)
        self.assertEqual(p, 200)
        self.assertEqual(c, 100)
        self.assertEqual(t, 300)

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_extract_model_none_response(self):
        """response 为 None 时返回 None。"""
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        model = TokenKeeperCallbackHandler._extract_model(None)
        self.assertIsNone(model)

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_extract_usage_empty_response(self):
        """空 response 返回 0。"""
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        p, c, t = TokenKeeperCallbackHandler._extract_usage(None)
        self.assertEqual(p, 0)
        self.assertEqual(c, 0)
        self.assertEqual(t, 0)

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_extract_usage_from_token_usage_attr(self):
        """从 token_usage 属性提取（langchain 0.3+）。"""
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        fake_resp = MagicMock()
        fake_resp.llm_output = {}  # 空 dict，不走第一条路
        fake_resp.token_usage = {
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "total_tokens": 75,
        }

        p, c, t = TokenKeeperCallbackHandler._extract_usage(fake_resp)
        self.assertEqual(p, 50)


class TestLangChainCallbackIntegration(unittest.TestCase):
    """集成测试：callback 记账到 ledger。"""

    def setUp(self):
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    @unittest.skip("需要 langchain-core 包，CI 环境不装")
    def test_on_llm_end_records_to_ledger(self):
        """on_llm_end 正确记账。"""
        from tokenkeeper import guard
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler
        from langchain_core.callbacks import BaseCallbackHandler

        with tempfile.TemporaryDirectory() as tmp:
            import os

            db_path = os.path.join(tmp, "test.db")
            guard.install(
                db_path=db_path,
                project="lc-test",
                user="tester",
                auto_patch_openai=False,
            )

            handler = TokenKeeperCallbackHandler(
                project="lc-test",
                user="tester",
                auto_install=False,
            )
            # 模拟 LLM 调用结束
            fake_resp = MagicMock()
            fake_resp.llm_output = {
                "model_name": "gpt-4o-mini",
                "token_usage": {
                    "prompt_tokens": 500,
                    "completion_tokens": 200,
                    "total_tokens": 700,
                },
            }
            handler._start_times["run-123"] = __import__("time").time()

            with patch.object(BaseCallbackHandler, "on_llm_end", return_value=None):
                handler.on_llm_end(fake_resp, run_id="run-123")

            # 验证记账
            records = guard.ledger().query(limit=10)
            self.assertGreaterEqual(len(records), 1, "应该有一条记账记录")
            r = records[0]
            self.assertEqual(r.model, "gpt-4o-mini")
            self.assertEqual(r.prompt_tokens, 500)
            self.assertEqual(r.completion_tokens, 200)
            self.assertGreater(r.cost_usd, 0)

            guard.uninstall()


if __name__ == "__main__":
    unittest.main()
