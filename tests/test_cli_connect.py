from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def test_connect_help_lists_supported_targets() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tokenkeeper.cli", "connect", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "hermes" in result.stdout
    assert "proxy" in result.stdout


def test_connect_hermes_dispatches_dashboard_when_db_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tokenkeeper import cli

    hermes_db = tmp_path / "state.db"
    hermes_db.touch()
    ledger_db = tmp_path / "tokenkeeper.db"
    captured: dict[str, Any] = {}

    def fake_run_dashboard(
        *,
        port: int,
        db: str,
        hermes_sync_since: str | None = None,
        hermes_db: str | None = None,
    ) -> None:
        captured.update(
            port=port,
            db=db,
            hermes_sync_since=hermes_sync_since,
            hermes_db=hermes_db,
        )

    monkeypatch.setattr(cli, "run_dashboard", fake_run_dashboard)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tokenkeeper",
            "connect",
            "hermes",
            "--db",
            str(ledger_db),
            "--port",
            "8502",
            "--since",
            "now",
            "--hermes-db",
            str(hermes_db),
        ],
    )

    cli.main()

    assert captured == {
        "port": 8502,
        "db": str(ledger_db),
        "hermes_sync_since": "now",
        "hermes_db": str(hermes_db.resolve()),
    }


def test_connect_hermes_fails_when_explicit_hermes_db_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tokenkeeper import cli

    missing_hermes_db = tmp_path / "missing-state.db"
    monkeypatch.setattr(
        cli,
        "run_dashboard",
        lambda **_kwargs: pytest.fail("dashboard should not start"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tokenkeeper",
            "connect",
            "hermes",
            "--hermes-db",
            str(missing_hermes_db),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "Hermes DB not found" in capsys.readouterr().err


def test_connect_proxy_dispatches_runtime_arguments_and_prints_base_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tokenkeeper import cli

    captured: dict[str, Any] = {}

    def fake_run_proxy(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("tokenkeeper.proxy.openai_compat.run_proxy", fake_run_proxy)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tokenkeeper",
            "connect",
            "proxy",
            "--upstream",
            "https://api.deepseek.com/v1",
            "--listen",
            "127.0.0.1:9999",
            "--db",
            str(tmp_path / "proxy.db"),
            "--project",
            "hermes",
            "--user",
            "me",
            "--upstream-auth-env",
            "DEEPSEEK_API_KEY",
            "--per-call-limit-usd",
            "0.5",
            "--budget-action",
            "warn",
        ],
    )

    cli.main()

    assert "base_url: http://127.0.0.1:9999/v1" in capsys.readouterr().out
    assert captured == {
        "listen": "127.0.0.1:9999",
        "upstream": "https://api.deepseek.com/v1",
        "db_path": str(tmp_path / "proxy.db"),
        "project": "hermes",
        "user": "me",
        "upstream_auth_env": "DEEPSEEK_API_KEY",
        "upstream_auth_header": "Authorization",
        "daily_limit_usd": None,
        "monthly_limit_usd": None,
        "per_call_limit_usd": 0.5,
        "budget_action": "warn",
    }


def test_connect_proxy_with_dashboard_cleans_up_child_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tokenkeeper import cli

    events: list[str] = []

    class FakeDashboardProcess:
        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: float | None = None) -> None:
            events.append(f"wait:{timeout}")

    def fake_popen(args: list[str]) -> FakeDashboardProcess:
        events.append("popen:" + " ".join(args))
        return FakeDashboardProcess()

    def fake_run_proxy(**_kwargs: Any) -> None:
        events.append("proxy")

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr("tokenkeeper.proxy.openai_compat.run_proxy", fake_run_proxy)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tokenkeeper",
            "connect",
            "proxy",
            "--upstream",
            "https://api.deepseek.com/v1",
            "--db",
            str(tmp_path / "proxy.db"),
            "--dashboard",
            "--port",
            "8502",
        ],
    )

    cli.main()

    assert events[0].startswith("popen:")
    assert "dashboard --port 8502 --db" in events[0]
    assert events[1:] == ["proxy", "terminate", "wait:5"]


def test_doctor_target_proxy_reports_ok_and_suggests_connect_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tokenkeeper import cli

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tokenkeeper",
            "doctor",
            "--target",
            "proxy",
            "--db",
            str(tmp_path / "doctor.db"),
            "--port",
            "0",
        ],
    )

    cli.main()

    output = capsys.readouterr().out
    assert "OK" in output
    assert "tokenkeeper connect proxy" in output


def test_doctor_target_hermes_fails_when_hermes_db_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tokenkeeper import cli

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tokenkeeper",
            "doctor",
            "--target",
            "hermes",
            "--hermes-db",
            str(tmp_path / "missing-state.db"),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "Hermes DB not found" in capsys.readouterr().out
