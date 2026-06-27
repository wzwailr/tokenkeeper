"""tokenkeeper Streamlit 看板。

启动方式::

    tokenkeeper dashboard

    # 或直接：
    streamlit run tokenkeeper/dashboard/app.py

功能：
- 顶部 KPI（总成本、调用次数、平均成本、错误率）
- 每日成本趋势（折线图）
- Top 烧钱排行（按模型）
- 最近调用列表（可筛选）
- 预算状态
"""

from __future__ import annotations

import sys
import os
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any

# 让 streamlit 能 import tokenkeeper 包
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from tokenkeeper import guard  # noqa: E402,F401
from tokenkeeper.ledger import Ledger  # noqa: E402
from tokenkeeper.pricing import PRICING_LAST_UPDATED, list_models  # noqa: E402


# ====================================================================
# 页面配置
# ====================================================================

st.set_page_config(
    page_title="tokenkeeper · 成本仪表盘",
    page_icon="🪶",
    layout="wide",
)


# ====================================================================
# 自定义 CSS（让看板更专业）
# ====================================================================

CUSTOM_CSS = """
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 0.95rem;
        color: #6c757d;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1.2rem 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .metric-card.green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .metric-card.orange { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
    .metric-card.blue { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }

    .metric-label {
        font-size: 0.85rem;
        opacity: 0.9;
        margin-bottom: 0.3rem;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        line-height: 1.1;
    }
    .metric-sub {
        font-size: 0.75rem;
        opacity: 0.8;
        margin-top: 0.3rem;
    }
</style>
"""


# ====================================================================
# 数据加载（缓存）
# ====================================================================


@st.cache_resource
def get_ledger(db_path: str) -> Any:
    """获取 Ledger 实例（按 db_path 缓存）。

    支持:
    - SQLite 文件路径: ./tokenkeeper.db
    - PostgreSQL URL: postgresql://user:pass@host:5432/db
    """
    if db_path.startswith("postgresql://") or db_path.startswith("postgres://"):
        from tokenkeeper.postgres_ledger import PostgresLedger

        return PostgresLedger(db_path)
    return Ledger(db_path)


# 实际调用时从配置文件读取路径（CLI 写入的）
def _get_db_path() -> str:
    """获取 DB 路径：优先读 CLI 写的临时配置，其次环境变量，最后默认。"""
    import json
    import tempfile

    cfg_path = os.path.join(tempfile.gettempdir(), "tokenkeeper_dashboard.json")
    try:
        with open(cfg_path) as f:
            cfg: dict[str, str] = json.load(f)
            raw = cfg.get(
                "db_path", os.environ.get("TOKENKEEPER_DB", "./tokenkeeper.db")
            )
            return os.path.expanduser(raw)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return os.environ.get("TOKENKEEPER_DB", "./tokenkeeper.db")


def _sync_hermes_for_dashboard(db_path: str | None = None) -> int:
    """Sync Hermes sessions into the dashboard's active SQLite ledger."""
    target_db = db_path or _get_db_path()
    if target_db.startswith("postgresql://") or target_db.startswith("postgres://"):
        return 0

    try:
        from tokenkeeper.integrations.hermes_connector import sync_hermes_to_tokenkeeper

        return sync_hermes_to_tokenkeeper(tk_db_path=target_db)
    except Exception:
        return 0


@st.cache_data(ttl=5)
def load_summary(group_by: str, days: int) -> list[dict]:
    """加载汇总数据（5 秒缓存）。"""
    ledger = get_ledger(_get_db_path())
    since = time.time() - days * 86400
    return ledger.summary(since=since, group_by=group_by)  # type: ignore[no-any-return]


@st.cache_data(ttl=5)
def load_total(days: int) -> tuple[float, float]:
    """加载总成本。"""
    ledger = get_ledger(_get_db_path())
    since = time.time() - days * 86400
    return ledger.total_cost(since=since)  # type: ignore[no-any-return]


@st.cache_data(ttl=5)
def load_calls(
    days: int,
    project: str | None,
    model: str | None,
    limit: int,
) -> list[dict]:
    """加载调用记录。"""
    ledger = get_ledger(_get_db_path())
    since = time.time() - days * 86400
    calls = ledger.query(since=since, project=project, model=model, limit=limit)
    return [
        {
            "时间": datetime.fromtimestamp(c.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            "项目": c.project,
            "用户": c.user,
            "模型": c.model,
            "输入": c.prompt_tokens,
            "输出": c.completion_tokens,
            "缓存": c.cached_tokens,
            "成本 (USD)": round(c.cost_usd, 6),
            "成本 (CNY)": round(c.cost_cny, 4),
            "延迟 (ms)": round(c.latency_ms, 1),
            "状态": c.status,
        }
        for c in calls
    ]


@st.cache_data(ttl=5)
def load_daily(days: int) -> pd.DataFrame:
    """加载每日成本时间序列。"""
    ledger = get_ledger(_get_db_path())
    since = time.time() - days * 86400
    calls = ledger.query(since=since, limit=100_000)

    if not calls:
        return pd.DataFrame(columns=["date", "cost_usd", "calls"])

    df = pd.DataFrame(
        [
            {
                "date": datetime.fromtimestamp(c.timestamp).date(),
                "cost_usd": c.cost_usd,
                "calls": 1,
                "tokens": c.total_tokens,
            }
            for c in calls
        ]
    )
    return (
        df.groupby("date")
        .agg({"cost_usd": "sum", "calls": "sum", "tokens": "sum"})
        .reset_index()
    )


# ====================================================================
# 侧边栏
# ====================================================================


def render_sidebar() -> dict:
    """渲染侧边栏过滤器，返回筛选参数。"""
    with st.sidebar:
        st.markdown("### 🪶 tokenkeeper")
        st.markdown(f"价格更新：{PRICING_LAST_UPDATED}")

        st.markdown("---")
        st.markdown("### ⚙️ 筛选条件")

        days = st.slider("时间范围（天）", 1, 90, 7)

        # 项目筛选
        all_projects = _get_all_projects()
        project_options = ["全部"] + all_projects
        project_choice = st.selectbox("项目", project_options)
        project = None if project_choice == "全部" else project_choice

        # 模型筛选
        model_options = ["全部"] + list_models()
        model_choice = st.selectbox("模型", model_options)
        model = None if model_choice == "全部" else model_choice

        st.markdown("---")
        st.markdown("### 📖 文档")
        st.markdown("- [README](https://github.com/wzwailr/tokenkeeper)")
        st.markdown(
            "- [使用示例](https://github.com/wzwailr/tokenkeeper/blob/master/examples)"
        )

    return {"days": days, "project": project, "model": model}


@st.cache_data(ttl=10)
def _get_all_projects() -> list[str]:
    """获取所有项目列表。"""
    ledger = get_ledger(_get_db_path())
    rows = ledger.summary(group_by="project")
    return [r["group_key"] for r in rows]


# ====================================================================
# 主页面组件
# ====================================================================


def render_header() -> None:
    """渲染页面头部。"""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.markdown(
        '<p class="main-header">🪶 tokenkeeper · AI 成本仪表盘</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="sub-header">实时追踪每一次 LLM 调用的成本与限额</p>',
        unsafe_allow_html=True,
    )


def render_kpis(days: int) -> None:
    """渲染顶部 KPI 卡片。"""
    total_usd, total_cny = load_total(days)
    summary = load_summary(group_by="model", days=days)
    total_calls = sum(s["calls"] for s in summary) if summary else 0
    avg_cost = total_usd / total_calls if total_calls else 0
    errors = sum(s["errors"] for s in summary) if summary else 0
    error_rate = (errors / total_calls * 100) if total_calls else 0

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f'<div class="metric-card">'
            f'<div class="metric-label">💰 总成本</div>'
            f'<div class="metric-value">${total_usd:.4f}</div>'
            f'<div class="metric-sub">¥{total_cny:.4f}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f'<div class="metric-card green">'
            f'<div class="metric-label">📞 调用次数</div>'
            f'<div class="metric-value">{total_calls:,}</div>'
            f'<div class="metric-sub">最近 {days} 天</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f'<div class="metric-card blue">'
            f'<div class="metric-label">📊 平均成本</div>'
            f'<div class="metric-value">${avg_cost:.6f}</div>'
            f'<div class="metric-sub">每次调用</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            f'<div class="metric-card orange">'
            f'<div class="metric-label">⚠️ 错误率</div>'
            f'<div class="metric-value">{error_rate:.1f}%</div>'
            f'<div class="metric-sub">{errors} / {total_calls}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )


def render_daily_trend(days: int) -> None:
    """渲染每日成本趋势图。"""
    st.markdown("### 📈 每日成本趋势")
    df = load_daily(days)

    if df.empty:
        st.info("该时间段内没有数据。")
        return

    # 折线图
    st.line_chart(
        df,
        x="date",
        y="cost_usd",
        height=300,
        use_container_width=True,
    )

    # 表格形式也展示
    with st.expander("📊 查看每日数据表"):
        st.dataframe(
            df.rename(
                columns={
                    "date": "日期",
                    "cost_usd": "成本 (USD)",
                    "calls": "调用次数",
                    "tokens": "总 Token",
                }
            ),
            use_container_width=True,
        )


def render_top_models(days: int) -> None:
    """渲染 Top 烧钱模型排行。"""
    st.markdown("### 🏆 Top 烧钱模型")
    summary = load_summary(group_by="model", days=days)

    if not summary:
        st.info("该时间段内没有数据。")
        return

    df = pd.DataFrame(summary)
    df["cost_usd"] = df["cost_usd"].round(4)
    df["avg_latency_ms"] = df["avg_latency_ms"].round(1)

    # Top 10
    df_top = df.head(10)

    # 占比
    total = df["cost_usd"].sum()
    df_top["占比"] = (df_top["cost_usd"] / total * 100).round(1).astype(str) + "%"

    st.dataframe(
        df_top.rename(
            columns={
                "group_key": "模型",
                "calls": "调用次数",
                "prompt_tokens": "输入 token",
                "completion_tokens": "输出 token",
                "cached_tokens": "缓存 token",
                "total_tokens": "总 token",
                "cost_usd": "成本 (USD)",
                "cost_cny": "成本 (CNY)",
                "avg_latency_ms": "平均延迟 (ms)",
                "errors": "错误数",
                "blocked": "阻断数",
            }
        ),
        use_container_width=True,
    )

    # 饼图
    if len(df_top) > 0:
        st.markdown("#### 成本分布")
        st.bar_chart(
            df_top.set_index("group_key")["cost_usd"],
            height=300,
            use_container_width=True,
        )


def render_recent_calls(filters: dict) -> None:
    """渲染最近调用列表。"""
    st.markdown("### 📋 最近调用")
    calls = load_calls(
        days=filters["days"],
        project=filters["project"],
        model=filters["model"],
        limit=100,
    )

    if not calls:
        st.info("该筛选条件下没有数据。")
        return

    df = pd.DataFrame(calls)
    st.dataframe(df, use_container_width=True, height=400)

    # 导出按钮
    col1, col2 = st.columns([1, 5])
    with col1:
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 下载 CSV",
            data=csv,
            file_name=f"tokenkeeper_calls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )


def render_budget_status() -> None:
    """渲染预算状态。"""
    st.markdown("### 💰 预算状态")
    st.info(
        "💡 预算配置通过 `guard.set_budget(...)` 在代码中设置，"
        "或在 `~/.tokenkeeper/budgets.json` 配置文件中设置。"
    )

    ledger = get_ledger(_get_db_path())
    today_start = datetime.combine(date.today(), datetime.min.time()).timestamp()
    today_spend, _ = ledger.total_cost(since=today_start)

    # 这里展示一个简单的当日花费面板
    st.metric(
        label="今日已花费",
        value=f"${today_spend:.4f}",
        delta=None,
    )


# ====================================================================
# 主入口
# ====================================================================


def main() -> None:
    """Streamlit 看板主入口。"""
    _sync_hermes_for_dashboard()
    render_header()

    filters = render_sidebar()

    st.markdown("---")

    # KPI
    render_kpis(filters["days"])

    st.markdown("---")

    # 趋势
    render_daily_trend(filters["days"])

    st.markdown("---")

    # Top 模型
    render_top_models(filters["days"])

    st.markdown("---")

    # 预算状态
    render_budget_status()

    st.markdown("---")

    # 最近调用
    render_recent_calls(filters)


if __name__ == "__main__":
    main()
