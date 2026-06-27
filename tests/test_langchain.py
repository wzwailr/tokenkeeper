from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch


class TestLangChainCallback(unittest.TestCase):
    def setUp(self) -> None:
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_callback_can_be_created(self) -> None:
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        self.assertTrue(callable(TokenKeeperCallbackHandler))

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_extract_model_from_llm_output(self) -> None:
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
    def test_extract_usage_from_llm_output(self) -> None:
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
    def test_extract_model_none_response(self) -> None:
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        model = TokenKeeperCallbackHandler._extract_model(None)
        self.assertIsNone(model)

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_extract_usage_empty_response(self) -> None:
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        p, c, t = TokenKeeperCallbackHandler._extract_usage(None)
        self.assertEqual(p, 0)
        self.assertEqual(c, 0)
        self.assertEqual(t, 0)

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_extract_usage_from_token_usage_attr(self) -> None:
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        fake_resp = MagicMock()
        fake_resp.llm_output = {}
        fake_resp.token_usage = {
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "total_tokens": 75,
        }

        p, c, t = TokenKeeperCallbackHandler._extract_usage(fake_resp)
        self.assertEqual(p, 50)


class TestLangChainCallbackIntegration(unittest.TestCase):
    def setUp(self) -> None:
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    def tearDown(self) -> None:
        from tokenkeeper import guard

        if guard.is_installed():
            guard.uninstall()

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_on_llm_end_records_to_ledger(self) -> None:
        from tokenkeeper import guard
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(
                db_path=db_path,
                project="lc-test",
                user="tester",
                auto_patch_openai=False,
            )
            try:
                handler = TokenKeeperCallbackHandler(
                    project="lc-test",
                    user="tester",
                    auto_install=False,
                )
                fake_resp = MagicMock()
                fake_resp.llm_output = {
                    "model_name": "gpt-4o-mini",
                    "token_usage": {
                        "prompt_tokens": 500,
                        "completion_tokens": 200,
                        "total_tokens": 700,
                    },
                }
                handler._start_times["run-123"] = time.time()

                handler.on_llm_end(fake_resp, run_id="run-123")

                ledger = guard.ledger()
                self.assertIsNotNone(ledger)
                records = ledger.query(limit=10) if ledger else []
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].model, "gpt-4o-mini")
                self.assertEqual(records[0].prompt_tokens, 500)
                self.assertEqual(records[0].completion_tokens, 200)
                self.assertGreater(records[0].cost_usd, 0)
            finally:
                guard.uninstall()

    @patch("tokenkeeper.integrations.langchain.HAS_LANGCHAIN", True)
    def test_on_llm_error_records_error_text(self) -> None:
        from tokenkeeper import guard
        from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            guard.install(
                db_path=db_path,
                project="lc-test",
                user="tester",
                auto_patch_openai=False,
            )
            try:
                handler = TokenKeeperCallbackHandler(
                    project="lc-test",
                    user="tester",
                    auto_install=False,
                )
                handler._start_times["run-err"] = time.time()

                handler.on_llm_error(RuntimeError("model failed"), run_id="run-err")

                ledger = guard.ledger()
                self.assertIsNotNone(ledger)
                records = ledger.query(limit=10) if ledger else []
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].status, "error")
                self.assertEqual(records[0].error, "model failed")
            finally:
                guard.uninstall()


if __name__ == "__main__":
    unittest.main()
