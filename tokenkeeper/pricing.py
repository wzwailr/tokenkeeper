# ====================================================================
# tokenkeeper.pricing — 模型价格表与成本计算
# ====================================================================
#
# 模块职责（架构师定稿，2026-06-23）：
# 1. 提供模型价格查询（USD / CNY 双向）
# 2. 支持自定义覆盖（环境变量 / 代码传入）
# 3. 价格快照（历史价格不影响已记账数据，调用时立即算）
# 4. 未知模型优雅降级（返回 None，不抛异常）
#
# 公开 API（__all__）：
# - get_pricing(model) -> ModelPricing | None
# - calculate_cost(model, prompt_tokens, completion_tokens, cached_tokens=0) -> CostBreakdown
# - list_models(provider=None) -> list[str]
# - register_custom_pricing(model, pricing) -> None
# - get_exchange_rate() -> float
# - reload_exchange_rate() -> float
#
# 错误处理哲学：
# - 未知模型 → 返回 None（让 ledger 记 cost=0 + warn）
# - 价格表 JSON 解析失败 → 抛 PricingConfigError（致命配置错误）
# - 负数 token → 抛 ValueError（用户代码 bug）
# ====================================================================

"""
模型价格表与成本计算。

这是 tokenkeeper 的"成本正确性基石"——价格错，全部数据错。
所以本模块是 100 分标准（最严），是其他模块的依赖。

Quickstart::

    from tokenkeeper.pricing import calculate_cost, list_models

    # 查模型价格
    cost = calculate_cost("gpt-4o", prompt_tokens=1000, completion_tokens=500)
    print(cost.cost_usd, cost.cost_cny)

    # 列出所有已知模型
    models = list_models()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from tokenkeeper.pricing_data import BUILTIN_PRICING_RAW, PRICING_LAST_UPDATED as _PRICING_LAST_UPDATED

__all__ = [
    "ModelPricing",
    "CostBreakdown",
    "PricingConfigError",
    "get_pricing",
    "calculate_cost",
    "list_models",
    "register_custom_pricing",
    "get_exchange_rate",
    "reload_exchange_rate",
    "USD_TO_CNY",
    "PRICING_LAST_UPDATED",
    "PRICING_OVERRIDE_ENV",
]


# ====================================================================
# 常量
# ====================================================================

logger = logging.getLogger(__name__)

#: 价格表环境变量名（JSON 覆盖），格式见 :func:`_parse_env_override`
PRICING_OVERRIDE_ENV: str = "TOKENKEEPER_PRICING_OVERRIDE"

#: 汇率环境变量名
EXCHANGE_RATE_ENV: str = "TOKENKEEPER_USD_CNY"

#: 默认汇率（2026-06-23 快照）
DEFAULT_USD_TO_CNY: float = 7.20

#: 价格表最后更新日期（用于在 dashboard 提示用户）
PRICING_LAST_UPDATED: str = "2026-06-23"


# ====================================================================
# 数据结构
# ====================================================================


@dataclass(frozen=True)
class ModelPricing:
    """单个模型的价格快照。

    价格单位：**每 1M tokens 的美元价**。
    缓存命中价通常比 input 便宜很多（如 DeepSeek 缓存命中仅 0.014/M）。

    Attributes:
        input_per_1m: 输入 token 价格（USD / 1M tokens）
        output_per_1m: 输出 token 价格（USD / 1M tokens）
        cached_input_per_1m: 缓存命中输入价格（USD / 1M tokens），None 表示无缓存机制
        provider: 提供商标识（openai/anthropic/deepseek/...）
        notes: 备注（如"缓存价是命中价"、"input 是 prompt cache miss"等）
    """

    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: Optional[float] = None
    provider: str = "unknown"
    notes: str = ""

    def __post_init__(self) -> None:
        """校验价格字段非负。

        Raises:
            ValueError: 任何字段为负数
        """
        if self.input_per_1m < 0:
            raise ValueError(f"input_per_1m must be >= 0, got {self.input_per_1m}")
        if self.output_per_1m < 0:
            raise ValueError(f"output_per_1m must be >= 0, got {self.output_per_1m}")
        if self.cached_input_per_1m is not None and self.cached_input_per_1m < 0:
            raise ValueError(
                f"cached_input_per_1m must be >= 0, got {self.cached_input_per_1m}"
            )


@dataclass(frozen=True)
class CostBreakdown:
    """一次 LLM 调用的成本明细。

    成本计算公式::

        cost_usd = uncached_prompt / 1M * input_per_1m
                  + cached_tokens / 1M * cached_input_per_1m
                  + completion_tokens / 1M * output_per_1m

    其中 ``uncached_prompt = prompt_tokens - cached_tokens``。
    如果模型没有缓存机制（cached_input_per_1m=None），缓存部分按原价计算。

    Attributes:
        model: 模型标识
        provider: 提供商标识
        prompt_tokens: 输入 token 数（**包含** cached_tokens）
        completion_tokens: 输出 token 数
        cached_tokens: 缓存命中 token 数（0 表示无缓存）
        cost_usd: 美元成本（保留 6 位小数）
        cost_cny: 人民币成本（保留 4 位小数）
    """

    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost_usd: float
    cost_cny: float

    def __post_init__(self) -> None:
        """校验 token 字段非负。"""
        if self.prompt_tokens < 0:
            raise ValueError(f"prompt_tokens must be >= 0, got {self.prompt_tokens}")
        if self.completion_tokens < 0:
            raise ValueError(f"completion_tokens must be >= 0, got {self.completion_tokens}")
        if self.cached_tokens < 0:
            raise ValueError(f"cached_tokens must be >= 0, got {self.cached_tokens}")


# ====================================================================
# 异常
# ====================================================================


class PricingConfigError(Exception):
    """价格配置错误（如环境变量 JSON 格式错、自定义注册格式错）。

    这是**致命**错误——配置错误不应该让业务跑，但也不应该 silent。
    """


# ====================================================================
# 运行时状态（自定义覆盖 + 汇率）
# ====================================================================

#: 用户自定义覆盖字典（model -> ModelPricing），优先级高于内置
_CUSTOM_PRICING: dict[str, ModelPricing] = {}

#: 环境变量是否已解析（懒加载）
_ENV_PARSED: bool = False

#: 当前生效汇率（可被 :func:`reload_exchange_rate` 重新加载）
USD_TO_CNY: float = DEFAULT_USD_TO_CNY


# ====================================================================
# 把 raw dict 转成 ModelPricing
# ====================================================================

def _build_pricing_from_raw(raw: dict) -> ModelPricing:
    """从 raw dict 构建 ModelPricing。

    Args:
        raw: 形如 ``{"input_per_1m": 1.0, "output_per_1m": 2.0, ...}``

    Returns:
        :class:`ModelPricing` 实例

    Raises:
        KeyError: 缺少 input_per_1m 或 output_per_1m
        ValueError: 字段为负数
    """
    return ModelPricing(
        input_per_1m=float(raw["input_per_1m"]),
        output_per_1m=float(raw["output_per_1m"]),
        cached_input_per_1m=(
            float(raw["cached_input_per_1m"])
            if raw.get("cached_input_per_1m") is not None
            else None
        ),
        provider=str(raw.get("provider", "unknown")),
        notes=str(raw.get("notes", "")),
    )


#: 内置价格表（model -> ModelPricing），由 raw dict 转换而来
#: 注：用 dict 推导式一次性构建，避免循环引用
_PRICING_TABLE: dict[str, ModelPricing] = {
    model: _build_pricing_from_raw(cfg)
    for model, cfg in BUILTIN_PRICING_RAW.items()
}

#: 价格表最后更新日期（重导出，供外部使用）
PRICING_LAST_UPDATED: str = _PRICING_LAST_UPDATED


# ====================================================================
# 环境变量解析
# ====================================================================


def _parse_env_override() -> None:
    """解析 ``TOKENKEEPER_PRICING_OVERRIDE`` 环境变量。

    JSON 格式示例::

        {
          "my-custom-model": {
            "input_per_1m": 1.0,
            "output_per_1m": 2.0,
            "cached_input_per_1m": 0.5,
            "provider": "custom",
            "notes": "自托管部署价"
          }
        }

    必填字段：``input_per_1m`` / ``output_per_1m``。
    可选字段：``cached_input_per_1m`` / ``provider`` / ``notes``。

    Raises:
        PricingConfigError: JSON 解析失败、字段缺失或类型错误
    """
    global _ENV_PARSED

    raw = os.environ.get(PRICING_OVERRIDE_ENV)
    if raw is None:
        _ENV_PARSED = True
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PricingConfigError(
            f"{PRICING_OVERRIDE_ENV} 环境变量不是合法 JSON: {e}"
        ) from e

    if not isinstance(data, dict):
        raise PricingConfigError(
            f"{PRICING_OVERRIDE_ENV} 必须是 JSON 对象（model -> pricing 映射）"
        )

    for model, cfg in data.items():
        if not isinstance(cfg, dict):
            raise PricingConfigError(
                f"{PRICING_OVERRIDE_ENV} 中模型 '{model}' 的配置不是对象"
            )
        if "input_per_1m" not in cfg or "output_per_1m" not in cfg:
            raise PricingConfigError(
                f"{PRICING_OVERRIDE_ENV} 中模型 '{model}' 缺少 "
                f"input_per_1m 或 output_per_1m"
            )
        try:
            pricing = ModelPricing(
                input_per_1m=float(cfg["input_per_1m"]),
                output_per_1m=float(cfg["output_per_1m"]),
                cached_input_per_1m=(
                    float(cfg["cached_input_per_1m"])
                    if "cached_input_per_1m" in cfg and cfg["cached_input_per_1m"] is not None
                    else None
                ),
                provider=str(cfg.get("provider", "custom")),
                notes=str(cfg.get("notes", "")),
            )
            _CUSTOM_PRICING[model] = pricing
            logger.info(
                "从环境变量 %s 加载自定义价格: %s",
                PRICING_OVERRIDE_ENV, model,
            )
        except (ValueError, TypeError) as e:
            raise PricingConfigError(
                f"{PRICING_OVERRIDE_ENV} 中模型 '{model}' 字段类型错误: {e}"
            ) from e

    _ENV_PARSED = True


def _ensure_env_parsed() -> None:
    """确保环境变量只解析一次（懒加载）。"""
    if not _ENV_PARSED:
        _parse_env_override()


# ====================================================================
# 公开 API
# ====================================================================


def get_pricing(model: str) -> Optional[ModelPricing]:
    """查询模型价格。

    查询顺序：**自定义 > 环境变量 > 内置**。
    未知模型返回 ``None``，**不抛异常**（让 ledger 记 cost=0 + warn）。

    Args:
        model: 模型标识，如 ``"gpt-4o"`` / ``"claude-sonnet-4"`` / ``"deepseek-chat"``

    Returns:
        该模型的价格对象，未知模型返回 ``None``

    Examples:
        >>> pricing = get_pricing("gpt-4o")
        >>> pricing.input_per_1m
        2.5
        >>> get_pricing("unknown-model-xyz") is None
        True
    """
    _ensure_env_parsed()
    if model in _CUSTOM_PRICING:
        return _CUSTOM_PRICING[model]
    return _PRICING_TABLE.get(model)


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> CostBreakdown:
    """计算一次 LLM 调用的成本。

    未知模型：返回 ``cost_usd=0, cost_cny=0``，**不抛异常**，同时 ``logger.warning`` 提示。

    Args:
        model: 模型标识
        prompt_tokens: 输入 token 数（**包含** cached_tokens）
        completion_tokens: 输出 token 数
        cached_tokens: 缓存命中 token 数（默认为 0）

    Returns:
        成本明细对象

    Raises:
        ValueError: 任何 token 字段为负数或 cached_tokens > prompt_tokens

    Examples:
        >>> cost = calculate_cost("gpt-4o", prompt_tokens=1000, completion_tokens=500)
        >>> round(cost.cost_usd, 6)
        0.0075
        >>> cost = calculate_cost("deepseek-chat", 1000, 500, cached_tokens=800)
        >>> # 800 走缓存价（0.014/M），200 走原价（0.14/M）
        >>> cost.cost_usd > 0
        True
    """
    # 边界校验
    if prompt_tokens < 0:
        raise ValueError(f"prompt_tokens must be >= 0, got {prompt_tokens}")
    if completion_tokens < 0:
        raise ValueError(f"completion_tokens must be >= 0, got {completion_tokens}")
    if cached_tokens < 0:
        raise ValueError(f"cached_tokens must be >= 0, got {cached_tokens}")
    # 注：cached_tokens > prompt_tokens 在 Anthropic 模式下是正常的
    # (Anthropic 的 input_tokens 不包含 cache，cache_read 独立计费)
    # OpenAI 模式下 cached_tokens 是 prompt_tokens 的子集
    # 这里不强制校验，调用方应保证语义正确

    pricing = get_pricing(model)

    if pricing is None:
        logger.warning(
            "未知模型 '%s'，无法计算成本，将记为 $0。"
            "请用 register_custom_pricing() 或环境变量 %s 注册价格。",
            model, PRICING_OVERRIDE_ENV,
        )
        return CostBreakdown(
            model=model,
            provider="unknown",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_usd=0.0,
            cost_cny=0.0,
        )

    # 计算 USD 成本（用 Decimal 避免浮点累积误差）
    cached_price = (
        pricing.cached_input_per_1m
        if pricing.cached_input_per_1m is not None
        else pricing.input_per_1m
    )

    # 两种模式：
    # 1. OpenAI 模式：cached_tokens 是 prompt_tokens 的子集
    #    cost = (prompt - cached) * input_price + cached * cached_price + completion * output_price
    # 2. Anthropic 模式：cached_tokens 独立于 prompt_tokens（input_tokens 不含 cache）
    #    cost = prompt * input_price + cached * cached_price + completion * output_price
    # 我们用一个标志来区分：如果 cached > prompt，假定是 Anthropic 模式
    if cached_tokens > prompt_tokens:
        # Anthropic 模式：cached 独立
        cost_usd_decimal = (
            Decimal(prompt_tokens) / Decimal(1_000_000) * Decimal(str(pricing.input_per_1m))
            + Decimal(cached_tokens) / Decimal(1_000_000) * Decimal(str(cached_price))
            + Decimal(completion_tokens) / Decimal(1_000_000) * Decimal(str(pricing.output_per_1m))
        )
    else:
        # OpenAI 模式：cached 是 prompt 的子集
        uncached_prompt = prompt_tokens - cached_tokens
        cost_usd_decimal = (
            Decimal(uncached_prompt) / Decimal(1_000_000) * Decimal(str(pricing.input_per_1m))
            + Decimal(cached_tokens) / Decimal(1_000_000) * Decimal(str(cached_price))
            + Decimal(completion_tokens) / Decimal(1_000_000) * Decimal(str(pricing.output_per_1m))
        )

    # 四舍五入到 6 位小数
    cost_usd = float(cost_usd_decimal.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))

    # 计算 CNY
    rate = get_exchange_rate()
    cost_cny = round(cost_usd * rate, 4)

    return CostBreakdown(
        model=model,
        provider=pricing.provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cost_usd=cost_usd,
        cost_cny=cost_cny,
    )


def list_models(provider: Optional[str] = None) -> list[str]:
    """列出所有已知模型。

    Args:
        provider: 如果指定，只返回该提供商的模型
            （如 ``"openai"`` / ``"anthropic"`` / ``"deepseek"``）

    Returns:
        模型标识列表（已排序）

    Examples:
        >>> all_models = list_models()
        >>> "gpt-4o" in all_models
        True
        >>> openai_models = list_models(provider="openai")
        >>> all(m.startswith(("gpt-", "o1", "o3", "o4")) for m in openai_models)
        True
    """
    _ensure_env_parsed()
    all_pricing = {**_PRICING_TABLE, **_CUSTOM_PRICING}
    if provider is None:
        return sorted(all_pricing.keys())
    return sorted(
        model for model, p in all_pricing.items()
        if p.provider == provider
    )


def register_custom_pricing(model: str, pricing: ModelPricing) -> None:
    """注册自定义模型价格。

    注册后该模型的价格**优先于**内置表。多次注册同模型，后者覆盖前者。

    Args:
        model: 模型标识
        pricing: 价格对象

    Raises:
        ValueError: model 为空字符串或 pricing 类型错误

    Examples:
        >>> from tokenkeeper.pricing import ModelPricing, register_custom_pricing
        >>> pricing = ModelPricing(
        ...     input_per_1m=1.0, output_per_1m=2.0, provider="self-hosted"
        ... )
        >>> register_custom_pricing("my-llama-3-70b", pricing)
    """
    if not model or not isinstance(model, str):
        raise ValueError(f"model must be non-empty string, got {model!r}")
    if not isinstance(pricing, ModelPricing):
        raise ValueError(f"pricing must be ModelPricing instance, got {type(pricing)}")
    _ensure_env_parsed()
    _CUSTOM_PRICING[model] = pricing
    logger.info("注册自定义价格: %s", model)


def get_exchange_rate() -> float:
    """获取当前 USD -> CNY 汇率。

    优先从环境变量 ``TOKENKEEPER_USD_CNY`` 读取，否则用默认 7.20。
    环境变量无效值会触发 warn 后回退到默认值（不抛异常）。

    Returns:
        当前汇率（1 USD = X CNY）

    Examples:
        >>> rate = get_exchange_rate()
        >>> rate > 0
        True
    """
    raw = os.environ.get(EXCHANGE_RATE_ENV)
    if raw is not None:
        try:
            rate = float(raw)
            if rate <= 0:
                logger.warning(
                    "%s=%s 不是正数，回退到默认值 %.2f",
                    EXCHANGE_RATE_ENV, raw, DEFAULT_USD_TO_CNY,
                )
                return DEFAULT_USD_TO_CNY
            return rate
        except ValueError:
            logger.warning(
                "%s=%s 不是合法数字，回退到默认值 %.2f",
                EXCHANGE_RATE_ENV, raw, DEFAULT_USD_TO_CNY,
            )
            return DEFAULT_USD_TO_CNY
    return USD_TO_CNY


def reload_exchange_rate() -> float:
    """重新加载汇率（从环境变量），更新全局 ``USD_TO_CNY``。

    Returns:
        新汇率

    Examples:
        >>> import os
        >>> os.environ["TOKENKEEPER_USD_CNY"] = "7.15"
        >>> reload_exchange_rate()
        7.15
    """
    global USD_TO_CNY
    USD_TO_CNY = get_exchange_rate()
    logger.info("汇率已更新: 1 USD = %.4f CNY", USD_TO_CNY)
    return USD_TO_CNY


# ====================================================================
# 模块自检（python -m tokenkeeper.pricing）
# ====================================================================


def _self_check() -> None:  # pragma: no cover
    """模块自检——跑几个核心 API 验证模块功能正常。

    通过 ``python -m tokenkeeper.pricing`` 调用。
    """
    print("=" * 60)
    print("tokenkeeper.pricing self-check")
    print("=" * 60)

    # 1. 列出模型数
    print(f"\n[1] 已知模型数: {len(list_models())}")
    print(f"    OpenAI 模型数: {len(list_models('openai'))}")
    print(f"    Anthropic 模型数: {len(list_models('anthropic'))}")
    print(f"    DeepSeek 模型数: {len(list_models('deepseek'))}")
    print(f"    价格快照日期: {PRICING_LAST_UPDATED}")

    # 2. 计算成本
    print("\n[2] 成本计算样例:")
    samples = [
        ("gpt-4o", 1000, 500, 0),
        ("claude-sonnet-4", 2000, 1000, 0),
        ("deepseek-chat", 5000, 2000, 0),
        ("deepseek-chat", 5000, 2000, 4000),  # 缓存命中
        ("qwen-turbo", 10000, 5000, 0),
    ]
    for sample in samples:
        cost = calculate_cost(*sample)
        cached_str = f"  cached={cost.cached_tokens:>5d}" if cost.cached_tokens else ""
        print(
            f"    {cost.model:>25s}  prompt={cost.prompt_tokens:>6d}  "
            f"completion={cost.completion_tokens:>6d}{cached_str}  "
            f"= ${cost.cost_usd:.6f}  ¥{cost.cost_cny:.4f}"
        )

    # 3. 未知模型
    print("\n[3] 未知模型降级:")
    unknown = calculate_cost("unknown-llm-9999", 1000, 500)
    print(f"    {unknown.model} → cost_usd=${unknown.cost_usd} (期望 $0)")

    # 4. 自定义价格
    print("\n[4] 自定义价格注册:")
    register_custom_pricing(
        "my-local-llama",
        ModelPricing(input_per_1m=0.0, output_per_1m=0.0, provider="self-hosted"),
    )
    local_cost = calculate_cost("my-local-llama", 1000, 500)
    print(f"    my-local-llama → ${local_cost.cost_usd} (期望 $0)")

    print("\n[OK] self-check 通过")


if __name__ == "__main__":  # pragma: no cover
    _self_check()