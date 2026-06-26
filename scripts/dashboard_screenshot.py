"""截屏 Streamlit 看板 — 不通过浏览器，用 AppTest 模拟。

streamlit.testing.v1.AppTest 允许我们在脚本里跑 streamlit 应用
并断言渲染输出。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, r"D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper")

# 设置 DB 路径环境变量（看板读这个）
os.environ["TOKENKEEPER_DB"] = (
    r"D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper\examples\demo.db"
)

from streamlit.testing.v1 import AppTest


def main():
    """跑 streamlit app 并打印渲染结果。"""
    app_path = r"D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper\tokenkeeper\dashboard\app.py"

    print("=" * 70)
    print("🪶 tokenkeeper 看板实际渲染效果")
    print("=" * 70)
    print()

    at = AppTest.from_file(app_path, default_timeout=30)
    at.run()

    if at.exception:
        print("❌ 异常:")
        for e in at.exception:
            print(f"  {e}")
        return

    print(
        f"✅ 渲染成功（{len(at.markdown)} 个 markdown 节点, {len(at.metric)} 个 metric, {len(at.dataframe)} 个 dataframe）"
    )
    print()
    print("=" * 70)
    print("📊 顶部 KPI 卡片（metrics）")
    print("=" * 70)
    for m in at.metric:
        label = m.label
        value = m.value
        delta = m.delta if hasattr(m, "delta") else None
        print(f"  📌 {label:20s}  →  {value}", end="")
        if delta:
            print(f"  (Δ {delta})", end="")
        print()

    print()
    print("=" * 70)
    print("📈 Markdown 标题")
    print("=" * 70)
    for md in at.markdown:
        text = str(md.value)[:120]
        print(f"  {text}")

    print()
    print("=" * 70)
    print("🏆 DataFrame 摘要（前 5 个）")
    print("=" * 70)
    for i, df in enumerate(at.dataframe):
        print(f"\n[DataFrame #{i + 1}]")
        print(df.value.head(5).to_string())

    print()
    print("=" * 70)
    print("🎨 Sidebar 选项")
    print("=" * 70)
    for sel in at.selectbox:
        label = sel.label
        options = sel.options
        print(f"  {label}: {len(options)} 个选项 ({options[:3]}...)")

    for sl in at.slider:
        print(f"  Slider '{sl.label}': range [{sl.min}, {sl.max}], 当前={sl.value}")

    print()
    print("=" * 70)
    print("[OK] 截屏完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
