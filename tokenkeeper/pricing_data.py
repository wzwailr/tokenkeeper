"""内置模型价格表（2026-06-23 快照，raw dict 形式）。

本文件**只放数据**，不放逻辑，**不依赖** :mod:`tokenkeeper.pricing`。
这样 :mod:`tokenkeeper.pricing` 可以从这里导入数据，反向避免循环引用。

数据格式::

    {
      "model-name": {
        "input_per_1m": 1.0,            # 必填
        "output_per_1m": 2.0,           # 必填
        "cached_input_per_1m": 0.5,     # 可选，None 表示无缓存
        "provider": "openai",           # 可选
        "notes": "..."                  # 可选
      }
    }

维护原则（docs/PROJECT_PLAN.md 4.2）：
- 每周手动 review 官方价格
- 价格变更时更新 ``PRICING_LAST_UPDATED``
- 价格错误时通过环境变量 ``TOKENKEEPER_PRICING_OVERRIDE`` 临时覆盖

数据来源：各模型官方公开价目表。
"""

from __future__ import annotations

from typing import TypedDict, Optional

__all__ = ["BUILTIN_PRICING_RAW", "PRICING_LAST_UPDATED"]


class PricingDict(TypedDict, total=False):
    """单个模型的 raw 价格字典（不含 ModelPricing 包装）。"""

    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: Optional[float]
    provider: str
    notes: str


#: 价格表最后更新日期
PRICING_LAST_UPDATED: str = "2026-06-25"

#: 内置价格表 raw 字典（model_name -> PricingDict）
#: 由 :mod:`tokenkeeper.pricing` 启动时转为 :class:`ModelPricing`
BUILTIN_PRICING_RAW: dict[str, PricingDict] = {
    # ---------------- OpenAI ----------------
    "gpt-4o": {
        "input_per_1m": 2.50, "output_per_1m": 10.00,
        "cached_input_per_1m": 1.25,  # 缓存命中 50% off
        "provider": "openai",
        "notes": "GPT-4o 标准版",
    },
    "gpt-4o-mini": {
        "input_per_1m": 0.15, "output_per_1m": 0.60,
        "cached_input_per_1m": 0.075,
        "provider": "openai",
        "notes": "GPT-4o 廉价版",
    },
    "gpt-4.1": {
        "input_per_1m": 2.00, "output_per_1m": 8.00,
        "cached_input_per_1m": 0.50,
        "provider": "openai",
        "notes": "GPT-4.1",
    },
    "gpt-4.1-mini": {
        "input_per_1m": 0.40, "output_per_1m": 1.60,
        "cached_input_per_1m": 0.10,
        "provider": "openai",
        "notes": "GPT-4.1 廉价版",
    },
    "gpt-4.1-nano": {
        "input_per_1m": 0.10, "output_per_1m": 0.40,
        "cached_input_per_1m": 0.025,
        "provider": "openai",
        "notes": "GPT-4.1 最便宜",
    },
    "o1": {
        "input_per_1m": 15.00, "output_per_1m": 60.00,
        "cached_input_per_1m": 7.50,
        "provider": "openai",
        "notes": "OpenAI o1 reasoning",
    },
    "o1-mini": {
        "input_per_1m": 1.10, "output_per_1m": 4.40,
        "cached_input_per_1m": 0.55,
        "provider": "openai",
        "notes": "o1 廉价版",
    },
    "o3": {
        "input_per_1m": 10.00, "output_per_1m": 40.00,
        "cached_input_per_1m": 2.50,
        "provider": "openai",
        "notes": "OpenAI o3",
    },
    "o3-mini": {
        "input_per_1m": 1.10, "output_per_1m": 4.40,
        "cached_input_per_1m": 0.55,
        "provider": "openai",
        "notes": "o3 廉价版",
    },
    "o4-mini": {
        "input_per_1m": 1.10, "output_per_1m": 4.40,
        "cached_input_per_1m": 0.275,
        "provider": "openai",
        "notes": "o4-mini",
    },

    # ---------------- Anthropic ----------------
    "claude-3-5-sonnet-20241022": {
        "input_per_1m": 3.00, "output_per_1m": 15.00,
        "cached_input_per_1m": 0.30,
        "provider": "anthropic",
        "notes": "Claude 3.5 Sonnet（2024-10）",
    },
    "claude-3-5-sonnet-latest": {
        "input_per_1m": 3.00, "output_per_1m": 15.00,
        "cached_input_per_1m": 0.30,
        "provider": "anthropic",
        "notes": "Claude 3.5 Sonnet（latest alias）",
    },
    "claude-3-5-haiku-20241022": {
        "input_per_1m": 0.80, "output_per_1m": 4.00,
        "cached_input_per_1m": 0.08,
        "provider": "anthropic",
        "notes": "Claude 3.5 Haiku",
    },
    "claude-3-7-sonnet": {
        "input_per_1m": 3.00, "output_per_1m": 15.00,
        "cached_input_per_1m": 0.30,
        "provider": "anthropic",
        "notes": "Claude 3.7 Sonnet",
    },
    "claude-sonnet-4": {
        "input_per_1m": 3.00, "output_per_1m": 15.00,
        "cached_input_per_1m": 0.30,
        "provider": "anthropic",
        "notes": "Claude Sonnet 4",
    },
    "claude-opus-4": {
        "input_per_1m": 15.00, "output_per_1m": 75.00,
        "cached_input_per_1m": 1.50,
        "provider": "anthropic",
        "notes": "Claude Opus 4（旗舰）",
    },
    "claude-haiku-4": {
        "input_per_1m": 1.00, "output_per_1m": 5.00,
        "cached_input_per_1m": 0.10,
        "provider": "anthropic",
        "notes": "Claude Haiku 4",
    },

    # ---------------- MiniMax（minimax） ----------------
    "MiniMax-M3": {
        "input_per_1m": 0.50,
        "output_per_1m": 2.00,
        "cached_input_per_1m": 0.05,
        "provider": "minimax",
        "notes": "MiniMax-M3（Frontier coding/agent 模型，默认开启 thinking）",
    },
    "MiniMax-M2.7": {
        "input_per_1m": 0.30,
        "output_per_1m": 1.20,
        "cached_input_per_1m": 0.03,
        "provider": "minimax",
        "notes": "MiniMax-M2.7（60 TPS）",
    },
    "MiniMax-M2.7-highspeed": {
        "input_per_1m": 0.30,
        "output_per_1m": 1.20,
        "cached_input_per_1m": 0.03,
        "provider": "minimax",
        "notes": "MiniMax-M2.7 极速版（100 TPS）",
    },
    "MiniMax-M2.5": {
        "input_per_1m": 0.20,
        "output_per_1m": 0.80,
        "cached_input_per_1m": 0.02,
        "provider": "minimax",
        "notes": "MiniMax-M2.5（性价比）",
    },
    "MiniMax-M2.5-highspeed": {
        "input_per_1m": 0.20,
        "output_per_1m": 0.80,
        "cached_input_per_1m": 0.02,
        "provider": "minimax",
        "notes": "MiniMax-M2.5 极速版",
    },
    "MiniMax-M2.1": {
        "input_per_1m": 0.10,
        "output_per_1m": 0.40,
        "cached_input_per_1m": 0.01,
        "provider": "minimax",
        "notes": "MiniMax-M2.1（多语言编程）",
    },
    "MiniMax-M2.1-highspeed": {
        "input_per_1m": 0.10,
        "output_per_1m": 0.40,
        "cached_input_per_1m": 0.01,
        "provider": "minimax",
        "notes": "MiniMax-M2.1 极速版",
    },
    "MiniMax-M2": {
        "input_per_1m": 0.05,
        "output_per_1m": 0.20,
        "cached_input_per_1m": 0.005,
        "provider": "minimax",
        "notes": "MiniMax-M2（编码/Agent 工作流）",
    },

    # ---------------- DeepSeek ----------------
    "deepseek-chat": {
        "input_per_1m": 0.14, "output_per_1m": 0.28,
        "cached_input_per_1m": 0.014,
        "provider": "deepseek",
        "notes": "DeepSeek V3 chat",
    },
    "deepseek-reasoner": {
        "input_per_1m": 0.55, "output_per_1m": 2.19,
        "cached_input_per_1m": 0.055,
        "provider": "deepseek",
        "notes": "DeepSeek R1 reasoning",
    },

    # ---------------- 阿里通义千问 ----------------
    "qwen-plus": {
        "input_per_1m": 0.80, "output_per_1m": 2.00,
        "provider": "alibaba",
        "notes": "通义千问 Plus",
    },
    "qwen-turbo": {
        "input_per_1m": 0.30, "output_per_1m": 0.60,
        "provider": "alibaba",
        "notes": "通义千问 Turbo（廉价）",
    },
    "qwen-max": {
        "input_per_1m": 2.00, "output_per_1m": 6.00,
        "provider": "alibaba",
        "notes": "通义千问 Max",
    },
    "qwen-long": {
        "input_per_1m": 0.50, "output_per_1m": 1.00,
        "provider": "alibaba",
        "notes": "通义千问 Long（长上下文）",
    },

    # ---------------- 智谱 ----------------
    "glm-4-plus": {
        "input_per_1m": 7.00, "output_per_1m": 7.00,
        "provider": "zhipu",
        "notes": "智谱 GLM-4 Plus",
    },
    "glm-4-flash": {
        "input_per_1m": 0.10, "output_per_1m": 0.10,
        "provider": "zhipu",
        "notes": "智谱 GLM-4 Flash（免费级）",
    },
    "glm-4-air": {
        "input_per_1m": 0.50, "output_per_1m": 0.50,
        "provider": "zhipu",
        "notes": "智谱 GLM-4 Air",
    },

    # ---------------- 百度文心 ----------------
    "ernie-4.0": {
        "input_per_1m": 1.20, "output_per_1m": 1.20,
        "provider": "baidu",
        "notes": "文心一言 4.0",
    },
    "ernie-3.5": {
        "input_per_1m": 0.40, "output_per_1m": 0.40,
        "provider": "baidu",
        "notes": "文心一言 3.5",
    },
    "ernie-speed": {
        "input_per_1m": 0.10, "output_per_1m": 0.10,
        "provider": "baidu",
        "notes": "文心一言 Speed（免费级）",
    },

    # ---------------- 月之暗面 ----------------
    "moonshot-v1-8k": {
        "input_per_1m": 1.00, "output_per_1m": 1.00,
        "provider": "moonshot",
        "notes": "Kimi 8k 上下文",
    },
    "moonshot-v1-32k": {
        "input_per_1m": 2.00, "output_per_1m": 2.00,
        "provider": "moonshot",
        "notes": "Kimi 32k 上下文",
    },
    "moonshot-v1-128k": {
        "input_per_1m": 5.00, "output_per_1m": 5.00,
        "provider": "moonshot",
        "notes": "Kimi 128k 上下文",
    },

    # ---------------- 零一万物 ----------------
    "yi-large": {
        "input_per_1m": 2.50, "output_per_1m": 2.50,
        "provider": "yi",
        "notes": "零一万物 Large",
    },
    "yi-medium": {
        "input_per_1m": 0.50, "output_per_1m": 0.50,
        "provider": "yi",
        "notes": "零一万物 Medium",
    },
}