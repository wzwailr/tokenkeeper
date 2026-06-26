"""tokenkeeper.integrations.openai_compat — OpenAI 兼容协议拦截器。

模块职责（架构师定稿，2026-06-23）：
1. monkey-patch openai.resources.chat.completions.Completions.create
2. 拦截所有 OpenAI 兼容协议的调用（覆盖 OpenAI / DeepSeek / 智谱 / 通义 / 文心 / 月之暗面 / 零一万物）
3. 提取 usage 信息
4. 调用 pricing 计算成本
5. 调用 ledger 记录
6. 调用 guard 检查预算

设计：
- 只 patch create()，不 patch stream()（v2 再做）
- 支持 sync 模式（MVP）
- 异常路径也要记账（status=error）
- guard block 时抛 BudgetExceededError（业务决定怎么处理）

公开 API（__all__）：
- install(guard_api)
- uninstall()
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

__all__ = [
    "install",
    "uninstall",
]


logger = logging.getLogger(__name__)


# ====================================================================
# 全局状态
# ====================================================================

#: 保存原始 create 方法，用于 uninstall
_original_create: Optional[Any] = None

#: 保存 guard_api 引用
_guard_api: Optional[Any] = None


# ====================================================================
# 安装 / 卸载
# ====================================================================


def install(guard_api: Any) -> None:
    """patch OpenAI SDK 的 chat.completions.create。

    Args:
        guard_api: :class:`tokenkeeper.core.GuardAPI` 实例

    Raises:
        ImportError: openai 包未安装
    """
    global _original_create, _guard_api

    if _original_create is not None:
        logger.debug("OpenAI 已经 patch 过，跳过")
        return

    try:
        from openai.resources.chat import completions as _chat_completions
    except ImportError as e:
        logger.error("openai 包未安装，无法 patch: %s", e)
        raise

    _guard_api = guard_api

    # 保存原始方法
    Completions = _chat_completions.Completions
    _original_create = Completions.create

    # patch（带错误处理）
    try:
        Completions.create = _wrap_create  # type: ignore[assignment]
        logger.info("OpenAI Completions.create 已 patch")
    except Exception as e:
        # patch 失败，记录但继续运行（降级模式）
        logger.error("patch OpenAI Completions.create 失败: %s", e)
        logger.warning("tokenkeeper 降级模式：OpenAI 调用将不记账")
        # 不抛异常，让原 SDK 继续工作


def uninstall() -> None:
    """恢复原始 OpenAI SDK 方法。"""
    global _original_create, _guard_api

    if _original_create is None:
        return

    try:
        from openai.resources.chat import completions as _chat_completions

        Completions = _chat_completions.Completions
        Completions.create = _original_create
        logger.info("OpenAI Completions.create 已 unpatch")
    except ImportError:
        pass

    _original_create = None
    _guard_api = None


# ====================================================================
# 拦截包装
# ====================================================================


def _wrap_create(self, *args, **kwargs):
    """拦截 OpenAI chat.completions.create。

    流程：
    1. 提取 model（用于计费）
    2. 估算本次调用成本（基于输入长度 + 模型单价）
    3. guard.check() 决定 ALLOW / WARN / BLOCK
    4. 调用原始 create()
    5. 提取 resp.usage（真实 token）
    6. 计算实际成本
    7. ledger.record()

    支持流式（stream=True）：
    - 自动注入 stream_options={"include_usage": true}
    - 把流式响应包装成"记账的流"
    """
    if _guard_api is None:
        # 没装 tokenkeeper，直接调用原方法
        if _original_create is not None:
            return _original_create(self, *args, **kwargs)
        raise RuntimeError("tokenkeeper 未初始化")

    ledger = _guard_api.ledger()
    guard_instance = _guard_api.guard_instance()

    model = kwargs.get("model", "unknown")
    messages = kwargs.get("messages", [])
    is_stream = kwargs.get("stream", False)

    # 流式模式：自动注入 include_usage 以便最后 chunk 包含 usage
    if is_stream:
        # 检查用户是否已经设置了 stream_options
        existing_options = kwargs.get("stream_options", {})
        if "include_usage" not in existing_options:
            kwargs["stream_options"] = {**existing_options, "include_usage": True}

    # 估算输入 token 数（粗估，按字符数 / 4）
    estimated_prompt_tokens = _estimate_input_tokens(messages)
    estimated_cost = _estimate_cost(
        model, estimated_prompt_tokens, estimated_completion_tokens=500
    )

    # guard 检查
    project = _guard_api._project
    user = _guard_api._user

    if guard_instance is not None:
        # guard 检查带重试
        decision = None
        for attempt in range(3):  # 最多 3 次（1 次原始 + 2 次重试）
            try:
                decision = guard_instance.check(
                    estimated_cost=estimated_cost,
                    project=project,
                    user=user,
                )
                break
            except Exception as e:
                if attempt < 2:  # 还有重试机会
                    logger.warning(
                        "guard.check() 第 %d 次失败，重试中: %s", attempt + 1, e
                    )
                    time.sleep(0.5)  # 等待 500ms 再重试
                else:
                    # 重试 2 次仍失败，fail-open
                    logger.error("guard.check() 重试 2 次后仍失败，跳过检查: %s", e)
                    decision = None

        if isinstance(decision, type(Exception())):
            # 已经是 BudgetExceededError（block 触发）
            raise

    # 调用原始方法（带网络重试）
    t0 = time.time()
    error_msg: Optional[str] = None
    status = "success"
    resp = None
    for attempt in range(3):  # 最多 3 次重试
        try:
            resp = _original_create(self, *args, **kwargs)
            break
        except Exception as e:
            if attempt < 2:  # 还有重试机会
                logger.warning("网络调用第 %d 次失败，重试中: %s", attempt + 1, e)
                time.sleep(1.0)  # 等待 1 秒再重试
            else:
                # 重试 2 次仍失败，记录错误并抛出
                latency_ms = (time.time() - t0) * 1000
                status = "error"
                error_msg = str(e)

                # 错误也要记账
                if ledger is not None:
                    try:
                        ledger.record(
                            _make_record(
                                model=model,
                                prompt_tokens=estimated_prompt_tokens,
                                completion_tokens=0,
                                cost_usd=0.0,
                                cost_cny=0.0,
                                latency_ms=latency_ms,
                                status=status,
                                error=error_msg,
                                project=project,
                                user=user,
                            )
                        )
                    except Exception as le:
                        logger.error("记录失败调用失败: %s", le)

                raise

    # 流式响应：包装成"记账的流"
    if is_stream:
        return _wrap_stream(resp, model, project, user, t0, ledger)

    # 非流式：正常处理
    latency_ms = (time.time() - t0) * 1000

    # 提取 usage
    prompt_tokens, completion_tokens, cached_tokens = _extract_usage(resp)
    actual_model = _extract_model(resp) or model

    # 计算实际成本
    from ..pricing import calculate_cost

    cost_breakdown = calculate_cost(
        model=actual_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
    )

    # 记账
    if ledger is not None:
        try:
            ledger.record(
                _make_record(
                    model=actual_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_breakdown.cost_usd,
                    cost_cny=cost_breakdown.cost_cny,
                    latency_ms=latency_ms,
                    status=status,
                    error=None,
                    project=project,
                    user=user,
                    cached_tokens=cached_tokens,
                )
            )
        except Exception as le:
            # 记账失败不能影响业务
            logger.error("记录成功调用失败: %s", le)

    return resp


def _wrap_stream(
    stream, model: str, project: str, user: str, t0: float, ledger: Optional[Any]
):
    """包装流式响应，迭代完后记账。

    OpenAI 流式工作原理：
    - stream 是 ChatCompletionChunk 的迭代器
    - 每个 chunk 有 choices[].delta.content（增量文本）
    - 最后一个 chunk 有 usage 字段（需 stream_options={"include_usage": true}）

    我们返回一个新的迭代器，包装原 stream，在迭代完后记账。
    """
    accumulated_content = []
    final_usage = None
    final_model = model
    error_occurred = None

    def _iterator():
        nonlocal final_usage, final_model, error_occurred
        try:
            for chunk in stream:
                # 收集 usage
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    final_usage = chunk.usage
                if hasattr(chunk, "model") and chunk.model:
                    final_model = chunk.model
                # 收集 content（可选，用于日志）
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        accumulated_content.append(delta.content)
                yield chunk
        except Exception as e:
            error_occurred = e
            raise
        finally:
            # 迭代完毕，记账
            _record_stream_usage(
                ledger,
                model,
                final_model,
                final_usage,
                project,
                user,
                t0,
                error_occurred,
            )

    return _iterator()


def _record_stream_usage(
    ledger: Optional[Any],
    requested_model: str,
    actual_model: str,
    usage: Optional[Any],
    project: str,
    user: str,
    t0: float,
    error: Optional[Exception],
):
    """流式结束后记账。"""
    if ledger is None:
        return
    latency_ms = (time.time() - t0) * 1000
    if error is not None:
        # 流式中途出错
        try:
            ledger.record(
                _make_record(
                    model=requested_model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost_usd=0.0,
                    cost_cny=0.0,
                    latency_ms=latency_ms,
                    status="error",
                    error=str(error),
                    project=project,
                    user=user,
                )
            )
        except Exception as le:
            logger.error("记录流式失败调用失败: %s", le)
        return

    # 成功：提取 usage
    prompt_tokens, completion_tokens, cached_tokens = 0, 0, 0
    if usage is not None:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached_tokens = getattr(details, "cached_tokens", 0) or 0

    # 计算成本
    from ..pricing import calculate_cost

    cost_breakdown = calculate_cost(
        model=actual_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
    )

    try:
        ledger.record(
            _make_record(
                model=actual_model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_breakdown.cost_usd,
                cost_cny=cost_breakdown.cost_cny,
                latency_ms=latency_ms,
                status="success",
                error=None,
                project=project,
                user=user,
                cached_tokens=cached_tokens,
            )
        )
    except Exception as le:
        logger.error("记录流式成功调用失败: %s", le)


# ====================================================================
# 辅助函数
# ====================================================================


def _estimate_input_tokens(messages: list) -> int:
    """粗估输入 token 数（按字符 / 4）。"""
    if not messages:
        return 0
    total_chars = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # 多模态：只算 text 字段
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total_chars += len(part.get("text", ""))
    # 粗估：1 token ≈ 4 字符（英文）；中文 1 token ≈ 1.5 字符
    # 折中按 3 字符/token
    return total_chars // 3


def _estimate_cost(
    model: str, prompt_tokens: int, estimated_completion_tokens: int
) -> float:
    """估算本次调用成本（粗估）。"""
    from ..pricing import calculate_cost

    try:
        breakdown = calculate_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=estimated_completion_tokens,
            cached_tokens=0,
        )
        return breakdown.cost_usd
    except Exception:
        return 0.0


def _extract_usage(resp: Any) -> tuple[int, int, int]:
    """从 OpenAI 响应提取 usage。

    Returns:
        (prompt_tokens, completion_tokens, cached_tokens)
    """
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return 0, 0, 0

        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0

        # cached_tokens 在 prompt_tokens_details.cached_tokens（新版本 OpenAI）
        cached_tokens = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached_tokens = getattr(details, "cached_tokens", 0) or 0

        return prompt_tokens, completion_tokens, cached_tokens
    except Exception as e:
        logger.warning("提取 usage 失败: %s", e)
        return 0, 0, 0


def _extract_model(resp: Any) -> Optional[str]:
    """从响应中提取真实模型名（用于按实际模型计费）。"""
    try:
        return getattr(resp, "model", None)
    except Exception:
        return None


def _make_record(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    cost_cny: float,
    latency_ms: float,
    status: str,
    error: Optional[str],
    project: str,
    user: str,
    cached_tokens: int = 0,
):
    """构造 CallRecord。"""
    from ..ledger import CallRecord

    return CallRecord(
        timestamp=time.time(),
        project=project,
        user=user,
        provider="openai",  # 默认；可被集成覆盖
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cost_usd=cost_usd,
        cost_cny=cost_cny,
        latency_ms=latency_ms,
        status=status,
        error=error,
    )
