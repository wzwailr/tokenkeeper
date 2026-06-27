"""Hermes HTTP 层拦截器 — 劫持 urllib 底层请求，实时记账。

原理:
- monkey-patch urllib.request.OpenerDirector.open
- 拦截所有 HTTP 请求
- 识别 OpenAI/Anthropic API 调用
- 提取 request body 中的 model/messages
- 提取 response body 中的 usage
- 写入 tokenkeeper ledger

用法:
    from tokenkeeper.integrations.hermes_http import install
    install(db_path="~/.hermes/tokenkeeper.db")
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from io import BytesIO
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["install", "uninstall"]

_original_open: Any = None
_guard_installed: bool = False
_callbacks: list = []

API_PATTERNS = [
    "/chat/completions",   # OpenAI compatible
    "/v1/messages",        # Anthropic
    "/v1/chat/completions",# DeepSeek / 国产模型
]


def install(db_path: str = "~/.hermes/tokenkeeper.db") -> bool:
    """安装 HTTP 拦截器。

    Returns:
        bool: 是否成功安装
    """
    global _original_open, _guard_installed
    import os

    # 确保 tokenkeeper 已安装
    try:
        from tokenkeeper.core import guard as api
        db = os.path.expanduser(db_path)
        if not api.is_installed():
            api.install(db_path=db, project="hermes", user="me")
            api.set_budget(daily_limit_usd=50.0, action="warn")
        _guard_installed = True
    except Exception as e:
        logger.error("tokenkeeper 初始化失败: %s", e)
        return False

    # 拦截 urllib
    if _original_open is not None:
        return True  # 已安装

    _original_open = urllib.request.OpenerDirector.open

    def _patched_open(self: Any, fullurl: Any, data: Any = None,
                      timeout: Any = None) -> Any:
        return _intercept_and_record(self, fullurl, data, timeout)

    urllib.request.OpenerDirector.open = _patched_open  # type: ignore
    logger.info("Hermes HTTP 拦截器已安装")
    return True


def uninstall() -> None:
    """卸载 HTTP 拦截器。"""
    global _original_open
    if _original_open is not None:
        urllib.request.OpenerDirector.open = _original_open
        _original_open = None
        logger.info("Hermes HTTP 拦截器已卸载")


def _intercept_and_record(self: Any, fullurl: Any, data: Any,
                          timeout: Any) -> Any:
    """拦截并记录 API 调用。"""
    url = str(fullurl) if hasattr(fullurl, 'full_url') else str(fullurl)

    # 检查是否是 LLM API 调用
    is_llm = any(p in url for p in API_PATTERNS)
    if not is_llm:
        return _original_open(self, fullurl, data, timeout)

    t0 = time.time()
    model = "unknown"
    prompt_estimate = 0

    # 提取请求信息
    if data is not None:
        try:
            body = data if isinstance(data, bytes) else data.encode()
            req = json.loads(body)
            model = req.get("model", "unknown")
            messages = req.get("messages", [])
            prompt_estimate = sum(len(str(m.get("content", ""))) // 4 for m in messages)
        except Exception:
            pass

    # 调用原始方法
    try:
        resp = _original_open(self, fullurl, data, timeout)
    except Exception as e:
        _record_call(model, 0, 0, "error", (time.time() - t0) * 1000)
        raise

    # 提取 response 中的 usage
    prompt_tokens = 0
    completion_tokens = 0
    try:
        body_text = resp.read()
        resp_data = json.loads(body_text)

        # OpenAI 格式
        usage = resp_data.get("usage", {})
        if usage:
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
        else:
            prompt_tokens = prompt_estimate

        # 重新封装 response（因为已经 read 了）
        resp = urllib.request.addinfourl(
            BytesIO(body_text) if isinstance(body_text, bytes) else BytesIO(body_text.encode()),
            resp.headers,
            resp.url,
            resp.code,
        )
    except Exception:
        prompt_tokens = prompt_estimate

    latency_ms = (time.time() - t0) * 1000
    _record_call(model, prompt_tokens, completion_tokens, "success", latency_ms)
    return resp


def _record_call(model: str, prompt: int, completion: int,
                 status: str, latency_ms: float) -> None:
    """记录调用到 tokenkeeper。"""
    try:
        from tokenkeeper.core import guard as api
        api.record(
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cost_usd=0,
            cost_cny=0,
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.debug("记账失败: %s", e)
