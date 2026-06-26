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
    cfg_path = os.path.join(tempfile.gettempdir(), "tokenkeeper_dashboard.json")
    with open(cfg_path, "w") as f:
        json.dump({"db_path": db}, f)

    dashboard_path = os.path.join(
        os.path.dirname(__file__),
        "dashboard",
        "app.py",
    )
    if not os.path.exists(dashboard_path):
        print(f"❌ 看板文件不存在: {dashboard_path}")
        sys.exit(1)

    sys.argv = ["streamlit", "run", dashboard_path, "--server.port", str(port)]
    stcli.main()


if __name__ == "__main__":
    main()
