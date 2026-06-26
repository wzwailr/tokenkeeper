"""tokenkeeper LangChain callback 集成。

用法::

    from tokenkeeper.integrations.langchain import TokenKeeperCallbackHandler

    llm = ChatOpenAI(
        model="gpt-4o",
        callbacks=[TokenKeeperCallbackHandler(project="my-app")],
    )

支持:
- on_llm_start: 提取 model 名，记录开始时间
- on_llm_end: 提取 token usage，计算成本，写入 ledger
- on_llm_error: 记录错误调用
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.outputs import LLMResult

    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False
    BaseCallbackHandler = object  # type: ignore
    LLMResult = None  # type: ignore

from tokenkeeper.pricing import calculate_cost

logger = logging.getLogger(__name__)

__all__ = ["TokenKeeperCallbackHandler"]


class TokenKeeperCallbackHandler(BaseCallbackHandler if HAS_LANGCHAIN else object):  # type: ignore
    """LangChain callback — 自动记账 LLM 调用。

    Args:
        project: 项目标识
        user: 用户标识
        auto_install: 是否自动调用 guard.install()（默认 True）
        db_path: DB 路径（仅首次 auto_install 时使用）
    """

    def __init__(
        self,
        project: str = "default",
        user: str = "default",
        auto_install: bool = True,
        db_path: str = "./tokenkeeper.db",
    ) -> None:
        if not HAS_LANGCHAIN:
            raise ImportError(
                "langchain-core 未安装。请运行: pip install tokenkeeper-ai[langchain]"
            )
        super().__init__()
        self._project = project
        self._user = user
        self._start_times: dict[str, float] = {}

        if auto_install:
            self._ensure_installed(db_path)

    def _ensure_installed(self, db_path: str) -> None:
        """确保 guard 已安装（幂等）。"""
        from tokenkeeper import guard

        if not guard.is_installed():
            guard.install(db_path=db_path, project=self._project, user=self._user)

    # ------------------------------------------------------------------
    # LangChain hook 实现
    # ------------------------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """LLM 调用开始 — 记录开始时间 + 估算输入 token。"""
        self._start_times[run_id] = time.time()

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """LLM 调用结束 — 提取 token usage 并记账。"""
        t0 = self._start_times.pop(run_id, time.time())
        latency_ms = (time.time() - t0) * 1000

        try:
            model = self._extract_model(response)
            prompt_tokens, completion_tokens, total_tokens = self._extract_usage(
                response
            )

            cost = calculate_cost(model or "unknown", prompt_tokens, completion_tokens)

            from tokenkeeper import guard

            guard.record(
                model=model or "unknown",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost.cost_usd,
                cost_cny=cost.cost_cny,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error("记账失败: %s", e)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """LLM 调用错误 — 记录失败的调用。"""
        t0 = self._start_times.pop(run_id, time.time())
        latency_ms = (time.time() - t0) * 1000

        try:
            from tokenkeeper import guard

            guard.record(
                model="unknown",
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=0,
                cost_cny=0,
                latency_ms=latency_ms,
                status="error",
            )
        except Exception as e:
            logger.error("记录错误调用失败: %s", e)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_model(response: Any) -> Optional[str]:
        """从 LLMResult 提取 model 名。"""
        if not response:
            return None
        # langchain 1.x: response.llm_output["model_name"]
        if hasattr(response, "llm_output") and isinstance(response.llm_output, dict):
            model = response.llm_output.get("model_name")
            if model:
                return model  # type: ignore[no-any-return]
        # 回退: 从 generations 中找
        if hasattr(response, "generations") and response.generations:
            for gen_list in response.generations:
                if gen_list:
                    first = gen_list[0]
                    if hasattr(first, "generation_info"):
                        model = (
                            first.generation_info.get("model_name")
                            if isinstance(first.generation_info, dict)
                            else None
                        )
                        if model:
                            return model  # type: ignore[no-any-return]
        return None

    @staticmethod
    def _extract_usage(response: Any) -> tuple[int, int, int]:
        """从 LLMResult 提取 token usage。

        Returns:
            (prompt_tokens, completion_tokens, total_tokens)
        """
        prompt = 0
        completion = 0
        total = 0

        if not response:
            return prompt, completion, total

        # 方式1: response.llm_output["token_usage"]
        if hasattr(response, "llm_output") and isinstance(response.llm_output, dict):
            usage = response.llm_output.get("token_usage", {})
            if isinstance(usage, dict):
                prompt = usage.get("prompt_tokens", 0)
                completion = usage.get("completion_tokens", 0)
                total = usage.get("total_tokens", prompt + completion)
                if total > 0:
                    return prompt, completion, total

        # 方式2: response.token_usage (langchain 0.3+)
        if hasattr(response, "token_usage"):
            tu = response.token_usage
            if isinstance(tu, dict):
                prompt = tu.get("prompt_tokens", 0)
                completion = tu.get("completion_tokens", 0)
                total = tu.get("total_tokens", prompt + completion)

        return prompt, completion, total
