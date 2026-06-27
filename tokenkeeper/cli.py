"""tokenkeeper 命令行入口。

命令：
- tokenkeeper dashboard    启动 Streamlit 看板
- tokenkeeper version      显示版本
- tokenkeeper info         显示运行时信息
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, _info


def main() -> None:
    """tokenkeeper CLI 主入口。"""
    parser = argparse.ArgumentParser(
        prog="tokenkeeper",
        description="AI API 成本监控与限流守护者",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # version
    subparsers.add_parser("version", help="显示版本")

    # info
    subparsers.add_parser("info", help="显示运行时信息")

    # dashboard
    dash_parser = subparsers.add_parser("dashboard", help="启动 Streamlit 看板")
    dash_parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="端口（默认 8501）",
    )
    dash_parser.add_argument(
        "--db",
        default="./tokenkeeper.db",
        help="SQLite DB 路径（默认 ./tokenkeeper.db）",
    )

    # proxy
    proxy_parser = subparsers.add_parser(
        "proxy",
        help="Run local HTTP proxy for external agents",
    )
    proxy_parser.add_argument(
        "--upstream",
        required=True,
        help="Upstream API base URL, for example https://api.openai.com/v1",
    )
    proxy_parser.add_argument(
        "--listen",
        default="127.0.0.1:8787",
        help="Listen address, default 127.0.0.1:8787",
    )
    proxy_parser.add_argument(
        "--db",
        default="./tokenkeeper.db",
        help="SQLite ledger path, default ./tokenkeeper.db",
    )
    proxy_parser.add_argument(
        "--project",
        default="default",
        help="Project name recorded in ledger",
    )
    proxy_parser.add_argument(
        "--user",
        default="default",
        help="User name recorded in ledger",
    )
    proxy_parser.add_argument(
        "--upstream-auth-env",
        default=None,
        help="Environment variable used to override upstream auth value",
    )
    proxy_parser.add_argument(
        "--upstream-auth-header",
        default="Authorization",
        help="Header name for upstream auth override, default Authorization",
    )
    proxy_parser.add_argument(
        "--daily-limit-usd",
        type=float,
        default=None,
        help="Optional daily budget limit in USD",
    )
    proxy_parser.add_argument(
        "--monthly-limit-usd",
        type=float,
        default=None,
        help="Optional monthly budget limit in USD",
    )
    proxy_parser.add_argument(
        "--per-call-limit-usd",
        type=float,
        default=None,
        help="Optional per-call budget limit in USD",
    )
    proxy_parser.add_argument(
        "--budget-action",
        choices=("warn", "block"),
        default="block",
        help="Budget behavior, default block",
    )

    args = parser.parse_args()

    if args.command == "version":
        print(f"tokenkeeper {__version__}")
    elif args.command == "info":
        import json

        info = _info()
        info["db_default"] = "./tokenkeeper.db"
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif args.command == "dashboard":
        run_dashboard(port=args.port, db=args.db)
    elif args.command == "proxy":
        from tokenkeeper.proxy.openai_compat import run_proxy

        run_proxy(
            listen=args.listen,
            upstream=args.upstream,
            db_path=args.db,
            project=args.project,
            user=args.user,
            upstream_auth_env=args.upstream_auth_env,
            upstream_auth_header=args.upstream_auth_header,
            daily_limit_usd=args.daily_limit_usd,
            monthly_limit_usd=args.monthly_limit_usd,
            per_call_limit_usd=args.per_call_limit_usd,
            budget_action=args.budget_action,
        )
    else:
        parser.print_help()
        sys.exit(1)


def run_dashboard(port: int, db: str) -> None:
    """启动 Streamlit 看板。"""
    try:
        import streamlit.web.cli as stcli
    except ImportError:
        print("❌ streamlit 未安装。\n请运行: pip install tokenkeeper[dashboard]")
        sys.exit(1)

    import os
    import json
    import tempfile

    # 写临时配置文件，看板进程通过它知道 DB 路径
    db_path = _resolve_dashboard_db_path(db)
    cfg_path = os.path.join(tempfile.gettempdir(), "tokenkeeper_dashboard.json")
    with open(cfg_path, "w") as f:
        json.dump({"db_path": db_path}, f)
    os.environ["TOKENKEEPER_DB"] = db_path

    dashboard_path = os.path.join(
        os.path.dirname(__file__),
        "dashboard",
        "app.py",
    )
    if not os.path.exists(dashboard_path):
        print(f"❌ 看板文件不存在: {dashboard_path}")
        sys.exit(1)

    # 自动安装 Hermes HTTP 拦截器
    try:
        from tokenkeeper.integrations.hermes_http import install as _install_http

        _install_http(db_path)
    except Exception:
        pass

    sys.argv = [
        "streamlit",
        "run",
        dashboard_path,
        "--server.port",
        str(port),
        "--",
        "--db",
        db_path,
    ]
    stcli.main()


def _resolve_dashboard_db_path(db: str) -> str:
    """Resolve dashboard SQLite paths before handing them to Streamlit."""
    import os

    if db.startswith(("postgresql://", "postgres://")):
        return db
    return os.path.abspath(os.path.expanduser(db))


if __name__ == "__main__":
    main()
