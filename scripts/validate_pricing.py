"""价格表验证脚本 — 检查数据一致性、合理范围、标注问题。

用法：
    python scripts/validate_pricing.py
    python scripts/validate_pricing.py --fix   # 自动修复明显错误
"""

from __future__ import annotations

import sys
from pathlib import Path

# 加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tokenkeeper.pricing_data import BUILTIN_PRICING_RAW, PRICING_LAST_UPDATED

# ====================================================================
# 验证规则
# ====================================================================


def validate():
    """验证所有价格并打印报告。返回 (errors, warnings, model_count)。"""
    errors: list[str] = []
    warnings: list[str] = []

    models = BUILTIN_PRICING_RAW
    model_count = len(models)

    # 按 provider 分组统计
    providers: dict[str, list[str]] = {}
    for name, p in models.items():
        prov = p.get("provider", "unknown")
        providers.setdefault(prov, []).append(name)

    print("=== tokenkeeper 价格验证报告 ===")
    print(f"最后更新: {PRICING_LAST_UPDATED}")
    print(f"模型总数: {model_count}")
    print(f"供应商数: {len(providers)}")
    print()

    # 1. 必填字段检查
    required = ["input_per_1m", "output_per_1m"]
    for name, p in models.items():
        for field in required:
            if field not in p or p[field] is None:
                errors.append(f"[{name}] 缺少必填字段 '{field}'")

    # 2. 价格合理性检查
    for name, p in models.items():
        inp = p.get("input_per_1m", 0)
        out = p.get("output_per_1m", 0)
        cached = p.get("cached_input_per_1m")

        # 输入价格应 ≥ 0
        if inp < 0:
            errors.append(f"[{name}] input_per_1m 不能为负数: {inp}")

        # 输出价格应 ≥ 输入价格（推理更贵）
        if out < inp:
            # some cheap models have flat pricing, this is just a warning
            if out > 0 and inp / out > 3:
                warnings.append(
                    f"[{name}] 输入价格({inp})远低于输出({out})，"
                    f"比例 {inp / out:.2f}，请确认"
                )

        # 缓存价格如果存在，应低于输入价格
        if cached is not None and cached >= inp:
            warnings.append(
                f"[{name}] cached_input_per_1m({cached}) 应小于 input_per_1m({inp})"
            )

        # provider 不能为空
        if not p.get("provider"):
            warnings.append(f"[{name}] 缺少 provider 字段")

    # 3. 检查是否有重复模型名
    seen = set()
    for name in models:
        if name.lower() in seen:
            warnings.append(f"[{name}] 模型名重复（大小写不敏感）")
        seen.add(name.lower())

    # 4. 按 provider 汇总
    print("--- 按供应商汇总 ---")
    for prov, model_names in sorted(providers.items()):
        total_models = len(model_names)
        # 采样第一个模型看价格范围
        sample = models[model_names[0]]
        price_range = f"${sample['input_per_1m']}~${sample['output_per_1m']}"
        print(f"  {prov:12s}  {total_models:2d} models  例: {price_range}/1M tokens")

    print()

    # 打印错误和警告
    if errors:
        print(f"❌ 错误 ({len(errors)}):")
        for e in errors:
            print(f"   {e}")
    else:
        print("✅ 无错误")

    if warnings:
        print(f"⚠️  警告 ({len(warnings)}):")
        for w in warnings:
            print(f"   {w}")
    else:
        print("✅ 无警告")

    print()
    print(f"总结: {model_count} models, {len(errors)} errors, {len(warnings)} warnings")

    return errors, warnings, model_count


# ====================================================================
# 修复已知问题
# ====================================================================


def fix_known_issues():
    """自动修复明显问题（价格取整等）。"""
    fixed = 0

    # Claude Sonnet 4 有多个日期变体，加 alias
    # （暂时无修复项）

    print(f"自动修复: {fixed} 项")
    return fixed


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="验证 tokenkeeper 价格表")
    parser.add_argument("--fix", action="store_true", help="自动修复明显错误")
    args = parser.parse_args()

    errors, warnings, count = validate()

    if args.fix:
        fix_known_issues()
        print()
        print("--- 修复后重新验证 ---")
        errors, warnings, count = validate()

    # 退出码: 0=ok, 1=有错误, 2=有警告
    if errors:
        sys.exit(1)
    elif warnings:
        sys.exit(2)
    else:
        sys.exit(0)
