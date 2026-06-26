"""tokenkeeper.integrations.anthropic — Anthropic 原生 SDK 拦截器。

模块职责（架构师定稿，2026-06-23）：
1. monkey-patch anthropic.resources.messages.Messages.create
2. 拦截 Anthropic 原生 SDK 调用（也覆盖通过 anthropic 库调 minimax 兼容端点）
3. 提取 usage 信息
4. 调用 pricing 计算成本
5. 调用 ledger 记录
6. 调用 guard 检查预算

设计：
- patch Messages.create（Anthropic SDK 1.x）
- 支持 sync 模式
- 错误路径也记账
- guard block 抛 BudgetExceededError

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
_original_anthropic_create: Optional[Any] = None

#: 保存 guard_api 引用
_guard_api: Optional[Any] = None


# ====================================================================
# 安装 / 卸载
# ====================================================================


def install(guard_api: Any) -> None:
    """patch Anthropic SDK 的 messages.create。

    Args:
        guard_api: :class:`tokenkeeper.core.GuardAPI` 实例

    Raises:
        ImportError: anthropic 包未安装
    """
    global _original_anthropic_create, _guard_api

    if _original_anthropic_create is not None:
        logger.debug("Anthropic 已经 patch 过，跳过")
        return

    # 如果 guard_api 是 None（降级模式），直接返回
    if guard_api is None:
        logger.warning("tokenkeeper 降级模式：Anthropic patch 跳过（无 guard_api）")
        return

    try:
        import anthropic
    except ImportError as e:
        logger.error("anthropic 包未安装，无法 patch: %s", e)
        raise

    _guard_api = guard_api

    # 保存原始方法
    try:
        _original_anthropic_create = anthropic.Anthropic().messages.create
    except Exception as e:
        # 获取原始方法失败，降级模式
        logger.error("获取 Anthropic 原始方法失败: %s", e)
        logger.warning("tokenkeeper 降级模式：Anthropic 调用将不记账")
        return

    # patch sync
    try:
        anthropic.Anthropic().messages.create = _wrap_create  # type: ignore[assignment]
        logger.info("Anthropic messages.create 已 patch")
    except Exception as e:
        logger.error("patch Anthropic messages.create 失败: %s", e)
        logger.warning("tokenkeeper 降级模式：Anthropic 调用将不记账")

    # patch async
    try:
        anthropic.AsyncAnthropic().messages.create = _wrap_async_create  # type: ignore[assignment]
        logger.info("Anthropic AsyncMessages.create 已 patch")
    except Exception as e:
        logger.error("patch Anthropic AsyncMessages.create 失败: %s", e)
        logger.warning("tokenkeeper 降级模式：Anthropic 异步调用将不记账")


def uninstall() -> None:
    """恢复原始 Anthropic SDK 方法。"""
    global _original_anthropic_create, _guard_api

    if _original_anthropic_create is None:
        return

    try:
        from anthropic.resources.messages import Messages

        Messages.create = _original_anthropic_create
        logger.info("Anthropic Messages.create 已 unpatch")
    except ImportError:
        pass

    _original_anthropic_create = None
    _guard_api = None


# ====================================================================
# 拦截包装
# ====================================================================


def _wrap_create(self, *args, **kwargs):
    """拦截 Anthropic messages.create。

    流程：
    1. 提取 model（用于计费）
    2. 估算本次调用成本（基于输入长度 + 模型单价）
    3. guard.check() 决定 ALLOW / WARN / BLOCK
    4. 调用原始 create()
    5. 提取 resp.usage（真实 token）
    6. 计算实际成本
    7. ledger.record()
    """
    if _guard_api is None:
        # 没装 tokenkeeper，直接调用原方法
        if _original_anthropic_create is not None:
            return _original_anthropic_create(self, *args, **kwargs)
        raise RuntimeError("tokenkeeper 未初始化")

    # 如果原始方法未定义（patch 失败），直接调用原方法
    if _original_anthropic_create is None:
        logger.warning("Anthropic patch 失败，直接调用原方法")
        # 这里需要动态获取原始方法
        try:
            import anthropic

            original_method = anthropic.Anthropic().messages.create
            return original_method(self, *args, **kwargs)
        except Exception as e:
            logger.error("获取原始方法失败: %s", e)
            raise

    ledger = _guard_api.ledger()
    guard_instance = _guard_api.guard_instance()

    model = kwargs.get("model", "unknown")
    messages = kwargs.get("messages", [])
    system = kwargs.get("system", None)

    # 估算输入 token 数（粗估）
    estimated_prompt_tokens = _estimate_input_tokens(messages, system)
    estimated_cost = _estimate_cost(
        model, estimated_prompt_tokens, estimated_completion_tokens=500
    )

    # guard 检查
    project = _guard_api._project
    user = _guard_api._user

    if guard_instance is not None:
        try:
            decision = guard_instance.check(
                estimated_cost=estimated_cost,
                project=project,
                user=user,
            )
        except Exception as e:
            # guard 内部错误不能让业务崩
            logger.error("guard.check() 失败，跳过: %s", e)
            decision = None

        if isinstance(decision, type(Exception())):
            # 已经是 BudgetExceededError（block 触发）
            raise

    # 调用原始方法
    t0 = time.time()
    error_msg: Optional[str] = None
    status = "success"
    try:
        resp = _original_anthropic_create(self, *args, **kwargs)
    except Exception as e:
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
    if kwargs.get("stream", False):
        return _wrap_anthropic_stream(resp, model, project, user, t0, ledger)

    # 非流式：正常处理
    latency_ms = (time.time() - t0) * 1000

    # 提取 usage（Anthropic 格式）
    input_tokens, output_tokens, cached_tokens = _extract_usage(resp)
    actual_model = _extract_model(resp) or model

    # 计算实际成本
    from ..pricing import calculate_cost

    cost_breakdown = calculate_cost(
        model=actual_model,
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )

    # 记账
    if ledger is not None:
        try:
            ledger.record(
                _make_record(
                    model=actual_model,
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
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


async def _wrap_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
    """拦截 Anthropic AsyncMessages.create — 异步版本。

    与 _wrap_create 共用核心逻辑，但调用路径为 async。
    """
    if _guard_api is None:
        if _original_anthropic_create is not None:
            return await _original_anthropic_create(self, *args, **kwargs)
        raise RuntimeError("tokenkeeper 未初始化")

    if _original_anthropic_create is None:
        import anthropic
        return await anthropic.AsyncAnthropic().messages.create(self, *args, **kwargs)

    ledger = _guard_api.ledger()
    guard_instance = _guard_api.guard_instance()
    model = kwargs.get("model", "unknown")
    messages = kwargs.get("messages", [])
    system = kwargs.get("system", None)
    estimated_prompt_tokens = _estimate_input_tokens(messages, system)
    estimated_cost = _estimate_cost(model, estimated_prompt_tokens, estimated_completion_tokens=500)

    if guard_instance is not None:
        try:
            from tokenkeeper.guard import BudgetExceededError
            guard_instance.check(estimated_cost=estimated_cost)
        except BudgetExceededError:
            raise
        except Exception:
            pass

    import time, asyncio
    t0 = time.time()
    error_msg = None
    status = "success"
    resp = None

    for attempt in range(3):
        try:
            resp = await _original_anthropic_create(self, *args, **kwargs)
            break
        except Exception as e:
            if attempt == 2:
                latency_ms = (time.time() - t0) * 1000
                status = "error"
                error_msg = str(e)
                _record_anthropic_stream(ledger, model, model, None,
                                         _guard_api._project, _guard_api._user, t0, error_msg)
                raise
            await asyncio.sleep(0.5 * (attempt + 1))

    latency_ms = (time.time() - t0) * 1000
    if resp is not None and status == "success":
        actual_model = _extract_model(resp) or model
        usage = _extract_usage(resp)
        cost = _estimate_cost(actual_model, usage[0], usage[1])
        try:
            ledger.record(_make_record(
                model=actual_model, prompt_tokens=usage[0],
                completion_tokens=usage[1], cost_usd=cost.cost_usd,
                cost_cny=cost.cost_cny, latency_ms=latency_ms,
                project=_guard_api._project, user=_guard_api._user,
            ))
        except Exception:
            pass

    return resp


def _wrap_anthropic_stream(
    stream: Any, model: str, project: str, user: str, t0: float, ledger: Any
) -> Any:
    """包装 Anthropic 流式响应。

    Anthropic SDK 的 stream 是 MessageStream 对象（不是普通迭代器）：
    - stream.__iter__() 产生 MessageStreamEvent
    - stream.until_done() 等待完成（会触发最终事件）
    - stream.get_final_message() 返回组装好的 Message（含 usage）

    我们返回 stream 本身，附加 done 回调记账。
    """
    if ledger is None:
        return stream

    # 注册 done 回调
    original_done = getattr(stream, "until_done", None)

    async def _wrapped_done() -> Any:
        """替代原始 until_done，记账后再返回。"""
        try:
            if original_done is not None:
                result = await original_done()
            else:
                result = None
        except Exception as e:
            _record_anthropic_stream(
                ledger, model, model, None, project, user, t0, str(e)
            )
            raise
        # 成功：提取 usage
        usage = getattr(result, "usage", None) if result else None
        actual_model = getattr(result, "model", model) if result else model
        _record_anthropic_stream(
            ledger, model, actual_model, usage, project, user, t0, None
        )
        return result

    # 替换 until_done
    if original_done is not None:
        stream.until_done = _wrapped_done

    # 同步场景：用户可能直接迭代 stream
    # 监听 __aiter__ / __iter__ 结束不优雅，
    # 但 Anthropic SDK 通常会调 get_final_message()
    return stream


def _record_anthropic_stream(
    ledger: Any,
    requested_model: str,
    actual_model: Optional[str],
    usage: Optional[tuple[int, int, int]],
    project: str,
    user: str,
    t0: float,
    error: Optional[str] = None,
) -> None:
    """记录 Anthropic 流式调用。"""
    if ledger is None:
        return
    latency_ms = (time.time() - t0) * 1000
    if error is not None:
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
            logger.error("记录 Anthropic 流式失败: %s", le)
        return

    input_tokens, output_tokens, cached_tokens = 0, 0, 0
    if usage is not None:
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cached_tokens = cache_read

    from ..pricing import calculate_cost

    cost_breakdown = calculate_cost(
        model=actual_model or "unknown",
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )

    try:
        ledger.record(
            _make_record(
                model=actual_model or "unknown",
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
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
        logger.error("记录 Anthropic 流式成功: %s", le)


# ====================================================================
# 辅助函数
# ====================================================================


def _estimate_input_tokens(messages: list, system: Any = None) -> int:
    """粗估输入 token 数（按字符 / 3）。"""
    total_chars = 0

    # 处理 system
    if isinstance(system, str):
        total_chars += len(system)
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    total_chars += len(block.get("text", ""))

    # 处理 messages
    if messages:
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    total_chars += len(content)
                elif isinstance(content, list):
                    # 多模态：只算 text
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            total_chars += len(part.get("text", ""))
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
    """从 Anthropic 响应提取 usage。

    Returns:
        (input_tokens, output_tokens, cached_tokens)
    """
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return 0, 0, 0

        # Anthropic 标准字段
        # input_tokens: 不包含 cache 的 input token
        # output_tokens: 输出 token
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        # Anthropic 的 cache 字段
        # cache_creation_input_tokens: 本次写入 cache 的 token（下次才走 cached 价）
        # cache_read_input_tokens: 本次从 cache 读的 token（按 cached 价）
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

        # 只把 cache_read 算作"已用缓存"
        cached_tokens = cache_read

        return input_tokens, output_tokens, cached_tokens
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
        provider="anthropic",  # 默认；可被具体集成覆盖
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
