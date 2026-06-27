from __future__ import annotations

import os

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
