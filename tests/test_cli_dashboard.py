from __future__ import annotations

import os
import tempfile

from tokenkeeper.cli import _resolve_dashboard_db_path


def test_resolve_dashboard_db_path_makes_sqlite_paths_absolute(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert _resolve_dashboard_db_path("tokenkeeper.db") == str(
        (tmp_path / "tokenkeeper.db").resolve()
    )


def test_resolve_dashboard_db_path_keeps_postgres_urls() -> None:
    url = "postgresql://localhost/tokenkeeper"

    assert _resolve_dashboard_db_path(url) == url


def test_run_dashboard_passes_db_as_streamlit_script_arg(monkeypatch, tmp_path) -> None:
    import streamlit.web.cli as stcli

    from tokenkeeper import cli

    db_path = tmp_path / "tokenkeeper.db"
    captured = {}

    def fake_main() -> None:
        captured["argv"] = list(cli.sys.argv)

    monkeypatch.setattr(stcli, "main", fake_main)
    monkeypatch.setattr("tokenkeeper.integrations.hermes_http.install", lambda db: None)

    cli.run_dashboard(port=8765, db=str(db_path))

    resolved = str(db_path.resolve())
    assert captured["argv"][-2:] == ["--db", resolved]
    assert os.environ["TOKENKEEPER_DB"] == resolved


def test_run_dashboard_does_not_write_legacy_temp_config(
    monkeypatch,
    tmp_path,
) -> None:
    import streamlit.web.cli as stcli

    from tokenkeeper import cli

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(stcli, "main", lambda: None)
    monkeypatch.setattr("tokenkeeper.integrations.hermes_http.install", lambda db: None)

    cli.run_dashboard(port=8765, db=str(tmp_path / "tokenkeeper.db"))

    assert not (tmp_path / "tokenkeeper_dashboard.json").exists()


def test_run_dashboard_sets_hermes_sync_since(monkeypatch, tmp_path) -> None:
    import streamlit.web.cli as stcli

    from tokenkeeper import cli

    monkeypatch.setattr(cli.time, "time", lambda: 1782543000.0)
    monkeypatch.setattr(stcli, "main", lambda: None)
    monkeypatch.setattr("tokenkeeper.integrations.hermes_http.install", lambda db: None)

    cli.run_dashboard(
        port=8765,
        db=str(tmp_path / "tokenkeeper.db"),
        hermes_sync_since="now",
    )

    assert os.environ["TOKENKEEPER_HERMES_SYNC_SINCE"] == "1782543000.0"
