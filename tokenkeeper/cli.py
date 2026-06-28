"""Command line entrypoint for tokenkeeper."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__, _info


def main() -> None:
    """Run the tokenkeeper CLI."""
    parser = argparse.ArgumentParser(
        prog="tokenkeeper",
        description="AI API cost monitoring and budget guardrails.",
    )
    subparsers = parser.add_subparsers(dest="command", help="subcommands")

    subparsers.add_parser("version", help="show version")
    subparsers.add_parser("info", help="show runtime information")

    dash_parser = subparsers.add_parser("dashboard", help="start Streamlit dashboard")
    dash_parser.add_argument("--port", type=int, default=8501, help="default: 8501")
    dash_parser.add_argument(
        "--db",
        default="./tokenkeeper.db",
        help="SQLite DB path, default ./tokenkeeper.db",
    )
    dash_parser.add_argument(
        "--hermes-sync-since",
        default=None,
        help="Only auto-sync Hermes activity after this Unix timestamp, or 'now'.",
    )
    dash_parser.add_argument(
        "--hermes-db",
        default=None,
        help="Hermes state.db path used by dashboard auto-sync.",
    )

    proxy_parser = subparsers.add_parser(
        "proxy",
        help="run local HTTP proxy for external agents",
    )
    _add_proxy_runtime_args(proxy_parser)

    connect_parser = subparsers.add_parser(
        "connect",
        help="one-command setup for supported integration paths",
    )
    connect_subparsers = connect_parser.add_subparsers(
        dest="connect_target",
        help="integration target",
        required=True,
    )
    connect_hermes_parser = connect_subparsers.add_parser(
        "hermes",
        help="sync Hermes local state DB and start dashboard",
    )
    connect_hermes_parser.add_argument(
        "--db",
        default="./tokenkeeper.db",
        help="SQLite ledger path, default ./tokenkeeper.db",
    )
    connect_hermes_parser.add_argument(
        "--port",
        type=int,
        default=8502,
        help="dashboard port, default 8502",
    )
    connect_hermes_parser.add_argument(
        "--since",
        default=None,
        help="Only sync Hermes activity after this Unix timestamp, or 'now'.",
    )
    connect_hermes_parser.add_argument(
        "--hermes-db",
        default=None,
        help="Hermes state.db path; defaults to the standard Hermes location.",
    )

    connect_proxy_parser = connect_subparsers.add_parser(
        "proxy",
        help="start proxy, optionally with dashboard",
    )
    _add_proxy_runtime_args(connect_proxy_parser)
    connect_proxy_parser.add_argument(
        "--dashboard",
        action="store_true",
        help="also start dashboard in a child process",
    )
    connect_proxy_parser.add_argument(
        "--port",
        type=int,
        default=8502,
        help="dashboard port when --dashboard is used, default 8502",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="diagnose install, DB, Hermes, proxy, and dashboard readiness",
    )
    doctor_parser.add_argument(
        "--target",
        choices=("all", "hermes", "proxy"),
        default="all",
        help="checks to run, default all",
    )
    doctor_parser.add_argument(
        "--db",
        default="./tokenkeeper.db",
        help="SQLite ledger path, default ./tokenkeeper.db",
    )
    doctor_parser.add_argument(
        "--hermes-db",
        default=None,
        help="Hermes state.db path; defaults to the standard Hermes location.",
    )
    doctor_parser.add_argument(
        "--port",
        type=int,
        default=8502,
        help="dashboard port to check, default 8502",
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
        run_dashboard(
            port=args.port,
            db=args.db,
            hermes_sync_since=args.hermes_sync_since,
            hermes_db=args.hermes_db,
        )
    elif args.command == "proxy":
        _run_proxy_from_args(args)
    elif args.command == "connect" and args.connect_target == "hermes":
        run_connect_hermes(
            port=args.port,
            db=args.db,
            since=args.since,
            hermes_db=args.hermes_db,
        )
    elif args.command == "connect" and args.connect_target == "proxy":
        run_connect_proxy(
            listen=args.listen,
            upstream=args.upstream,
            db=args.db,
            project=args.project,
            user=args.user,
            upstream_auth_env=args.upstream_auth_env,
            upstream_auth_header=args.upstream_auth_header,
            daily_limit_usd=args.daily_limit_usd,
            monthly_limit_usd=args.monthly_limit_usd,
            per_call_limit_usd=args.per_call_limit_usd,
            budget_action=args.budget_action,
            dashboard=args.dashboard,
            port=args.port,
        )
    elif args.command == "doctor":
        status = run_doctor(
            target=args.target,
            db=args.db,
            hermes_db=args.hermes_db,
            port=args.port,
        )
        if status:
            sys.exit(status)
    else:
        parser.print_help()
        sys.exit(1)


def _add_proxy_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--upstream",
        required=True,
        help="Upstream API base URL, for example https://api.openai.com/v1",
    )
    parser.add_argument(
        "--listen",
        default="127.0.0.1:8787",
        help="Listen address, default 127.0.0.1:8787",
    )
    parser.add_argument(
        "--db",
        default="./tokenkeeper.db",
        help="SQLite ledger path, default ./tokenkeeper.db",
    )
    parser.add_argument(
        "--project",
        default="default",
        help="Project name recorded in ledger",
    )
    parser.add_argument(
        "--user",
        default="default",
        help="User name recorded in ledger",
    )
    parser.add_argument(
        "--upstream-auth-env",
        default=None,
        help="Environment variable used to override upstream auth value",
    )
    parser.add_argument(
        "--upstream-auth-header",
        default="Authorization",
        help="Header name for upstream auth override, default Authorization",
    )
    parser.add_argument(
        "--daily-limit-usd",
        type=float,
        default=None,
        help="Optional daily budget limit in USD",
    )
    parser.add_argument(
        "--monthly-limit-usd",
        type=float,
        default=None,
        help="Optional monthly budget limit in USD",
    )
    parser.add_argument(
        "--per-call-limit-usd",
        type=float,
        default=None,
        help="Optional per-call budget limit in USD",
    )
    parser.add_argument(
        "--budget-action",
        choices=("warn", "block"),
        default="block",
        help="Budget behavior, default block",
    )


def run_dashboard(
    port: int,
    db: str,
    hermes_sync_since: str | None = None,
    hermes_db: str | None = None,
) -> None:
    """Start the Streamlit dashboard."""
    try:
        import streamlit.web.cli as stcli
    except ImportError:
        print(
            "ERROR: streamlit is not installed.\n"
            "Install it with: pip install tokenkeeper-ai[dashboard]"
        )
        sys.exit(1)

    db_path = _resolve_dashboard_db_path(db)
    os.environ["TOKENKEEPER_DB"] = db_path
    resolved_hermes_sync_since = _resolve_hermes_sync_since(hermes_sync_since)
    if resolved_hermes_sync_since is not None:
        os.environ["TOKENKEEPER_HERMES_SYNC_SINCE"] = resolved_hermes_sync_since
    if hermes_db is not None:
        os.environ["TOKENKEEPER_HERMES_DB"] = str(_resolve_hermes_db_path(hermes_db))

    dashboard_path = os.path.join(
        os.path.dirname(__file__),
        "dashboard",
        "app.py",
    )
    if not os.path.exists(dashboard_path):
        print(f"ERROR: dashboard file not found: {dashboard_path}")
        sys.exit(1)

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


def run_connect_hermes(
    *,
    port: int,
    db: str,
    since: str | None = None,
    hermes_db: str | None = None,
) -> None:
    """Validate Hermes state DB and start a sync-enabled dashboard."""
    hermes_path = _resolve_hermes_db_path(hermes_db)
    if not hermes_path.exists():
        print(f"Hermes DB not found: {hermes_path}", file=sys.stderr)
        print(
            "Start Hermes once, or pass the correct path with --hermes-db PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Hermes DB: {hermes_path}")
    print(f"Dashboard: http://127.0.0.1:{port}")
    run_dashboard(
        port=port,
        db=db,
        hermes_sync_since=since,
        hermes_db=str(hermes_path),
    )


def run_connect_proxy(
    *,
    listen: str,
    upstream: str,
    db: str,
    project: str,
    user: str,
    upstream_auth_env: str | None,
    upstream_auth_header: str,
    daily_limit_usd: float | None,
    monthly_limit_usd: float | None,
    per_call_limit_usd: float | None,
    budget_action: str,
    dashboard: bool,
    port: int,
) -> None:
    """Start the accounting proxy and optionally a dashboard child process."""
    base_url = _proxy_base_url(listen)
    print(f"base_url: {base_url}")
    print("Configure your agent's OpenAI-compatible base_url to this value.")

    dashboard_process: Any = None
    if dashboard:
        print(f"Dashboard: http://127.0.0.1:{port}")
        dashboard_process = _start_dashboard_process(port=port, db=db)

    try:
        _run_proxy(
            listen=listen,
            upstream=upstream,
            db_path=db,
            project=project,
            user=user,
            upstream_auth_env=upstream_auth_env,
            upstream_auth_header=upstream_auth_header,
            daily_limit_usd=daily_limit_usd,
            monthly_limit_usd=monthly_limit_usd,
            per_call_limit_usd=per_call_limit_usd,
            budget_action=budget_action,
        )
    finally:
        if dashboard_process is not None:
            _stop_dashboard_process(dashboard_process)


def run_doctor(
    *,
    target: str = "all",
    db: str = "./tokenkeeper.db",
    hermes_db: str | None = None,
    port: int = 8502,
) -> int:
    """Run local readiness checks and print actionable next commands."""
    checks: list[tuple[str, str]] = []

    checks.append(("OK", f"tokenkeeper version {__version__}"))
    checks.append(_db_path_check(db))
    checks.append(_port_check(port))

    if target in ("all", "hermes"):
        checks.append(_dashboard_dependency_check(required=target == "hermes"))
        checks.append(_hermes_db_check(hermes_db, required=target == "hermes"))

    if target in ("all", "proxy"):
        checks.append(("OK", "proxy runtime uses the Python standard library"))

    for status, message in checks:
        print(f"{status}: {message}")

    print()
    print("Suggested commands:")
    if target in ("all", "hermes"):
        hermes_arg = ""
        if hermes_db:
            hermes_arg = f" --hermes-db {hermes_db}"
        print(
            "  tokenkeeper connect hermes "
            f"--db {db} --port {port} --since now{hermes_arg}"
        )
    if target in ("all", "proxy"):
        print(
            "  tokenkeeper connect proxy "
            "--upstream https://api.deepseek.com/v1 "
            f"--listen 127.0.0.1:8787 --db {db} --project default --user default"
        )

    return 1 if any(status == "ERROR" for status, _message in checks) else 0


def _run_proxy_from_args(args: argparse.Namespace) -> None:
    _run_proxy(
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


def _run_proxy(**kwargs: Any) -> None:
    from tokenkeeper.proxy.openai_compat import run_proxy

    run_proxy(**kwargs)


def _start_dashboard_process(*, port: int, db: str) -> Any:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tokenkeeper.cli",
            "dashboard",
            "--port",
            str(port),
            "--db",
            db,
        ]
    )


def _stop_dashboard_process(process: Any) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _db_path_check(db: str) -> tuple[str, str]:
    if db.startswith(("postgresql://", "postgres://")):
        return ("OK", "PostgreSQL ledger URL configured")

    db_path = Path(os.path.expanduser(db)).resolve()
    parent = db_path.parent
    if not parent.exists():
        return ("ERROR", f"DB directory does not exist: {parent}")
    if not os.access(parent, os.W_OK):
        return ("ERROR", f"DB directory is not writable: {parent}")
    return ("OK", f"DB directory is writable: {parent}")


def _port_check(port: int) -> tuple[str, str]:
    if port == 0:
        return ("OK", "port 0 asks the OS to choose a free port")
    if _is_port_available(port):
        return ("OK", f"port {port} is available")
    return ("ERROR", f"port {port} is already in use")


def _dashboard_dependency_check(*, required: bool) -> tuple[str, str]:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        status = "ERROR" if required else "WARN"
        return (
            status,
            "streamlit is not installed; run: pip install tokenkeeper-ai[dashboard]",
        )
    return ("OK", "streamlit dashboard dependency is installed")


def _hermes_db_check(
    hermes_db: str | None,
    *,
    required: bool,
) -> tuple[str, str]:
    hermes_path = _resolve_hermes_db_path(hermes_db)
    if hermes_path.exists():
        return ("OK", f"Hermes DB found: {hermes_path}")

    status = "ERROR" if required else "WARN"
    return (
        status,
        f"Hermes DB not found: {hermes_path}",
    )


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _proxy_base_url(listen: str) -> str:
    if listen.startswith(("http://", "https://")):
        return listen.rstrip("/") + "/v1"

    host, separator, port = listen.rpartition(":")
    if not separator:
        return f"http://{listen}/v1"

    public_host = "127.0.0.1" if host in ("", "0.0.0.0") else host
    return f"http://{public_host}:{port}/v1"


def _resolve_dashboard_db_path(db: str) -> str:
    """Resolve dashboard SQLite paths before handing them to Streamlit."""
    if db.startswith(("postgresql://", "postgres://")):
        return db
    return os.path.abspath(os.path.expanduser(db))


def _resolve_hermes_db_path(hermes_db: str | None = None) -> Path:
    if hermes_db:
        return Path(os.path.expanduser(hermes_db)).resolve()

    from tokenkeeper.integrations.hermes_connector import _get_hermes_db

    return _get_hermes_db()


def _resolve_hermes_sync_since(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "now":
        return str(time.time())
    float(value)
    return value


if __name__ == "__main__":
    main()
